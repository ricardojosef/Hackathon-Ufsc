import unittest
from unittest.mock import patch

from classification import classify_group
from deduplication import FindingGroup
from models import Finding, FindingKind
from scoring import (
    EXPOENTE_ESFORCO_POR_TIER,
    LIMIAR_ALTO,
    LIMIAR_MEDIO,
    _priority_for_score,
    calculate_score,
    notes_for_group,
    rank_groups,
    score_priority_label,
)


class ScoringTests(unittest.TestCase):
    def make_group(
        self,
        concept,
        *,
        category="security",
        kind=FindingKind.FINDING,
        metric_value=None,
        severity="HIGH",
        file_path="file.py",
    ):
        finding = Finding(
            source_tool="radon" if kind == FindingKind.METRIC else "bandit",
            rule_id="radon.cc" if kind == FindingKind.METRIC else "B608",
            category=category,
            file_path=file_path,
            line=10,
            description=concept,
            kind=kind,
            metric_value=metric_value,
            severity=severity,
        )
        return classify_group(
            FindingGroup(
                concept=concept,
                representative_finding=finding,
                evidences=[finding],
            )
        )

    def test_security_concepts_receive_explicit_high_risk_score(self):
        result = calculate_score(self.make_group("dynamic_sql"))
        self.assertEqual(score_priority_label(result.score_priority), "high")
        # nota bruta 5.0 * peso_sev 1.0 (severidade HIGH)
        self.assertEqual(result.notes["seguranca"], 5.0)
        self.assertIn("aggravating_weights", result.factors)

    def test_tool_severity_scales_the_notes(self):
        # bandit reporta B105 (senha hardcoded) como LOW, apesar de ser credencial
        # real em producao. peso_sev corta a nota; o tier de prazo e quem garante
        # que o item nao desapareca da frente da fila.
        alto = calculate_score(self.make_group("hardcoded_secret", severity="HIGH"))
        baixo = calculate_score(self.make_group("hardcoded_secret", severity="LOW"))
        self.assertGreater(alto.score, 300)
        self.assertLess(baixo.score, alto.score)
        self.assertEqual(alto.factors["native_severity"], "HIGH")
        # a severidade muda o score, mas nao o prazo
        self.assertEqual(alto.deadline_tier, baixo.deadline_tier)

    def test_missing_timeout_and_swallowed_exception_have_policy_notes(self):
        timeout = calculate_score(self.make_group("missing_timeout", category="availability"))
        swallowed = calculate_score(self.make_group("swallowed_exception", category="reliability"))
        self.assertEqual(timeout.notes["aumento_problema"], 3.0)
        # reliability foi recalibrado para 4.0 no commit 086786d
        self.assertEqual(swallowed.notes["aumento_problema"], 4.0)
        # timeout ainda pontua mais: custa 0.5 ponto contra 1.0 do swallowed
        self.assertGreater(timeout.score, swallowed.score)

    def test_complexity_29_uses_metric_value(self):
        result = calculate_score(
            self.make_group(
                "cyclomatic_complexity",
                category="maintainability",
                kind=FindingKind.METRIC,
                metric_value=29,
                severity="F",
            )
        )
        # as notas sao cruas; a severidade entra uma vez sobre o produto
        self.assertEqual(result.notes["aumento_problema"], 4.0)
        # CC=29 usa metric_value, nao a letra do rank
        self.assertEqual(result.factors["peso_severidade"], 1.0)
        # refatorar funcao de CC=29 sem rede de testes custa 5 story points, e o
        # esforco derruba o score bruto: caro e sem prazo associado
        self.assertEqual(result.esforco_pontos, 5.0)
        self.assertEqual(result.score_priority, "baixo")

    def test_cheap_release_blocker_outscores_a_deadline_free_item(self):
        unused = calculate_score(self.make_group("unused_variable", category="code_quality"))
        # import_error bloqueia o release onde estiver (sem staging, deploy =
        # git pull) e custa 0.5 ponto: bloqueante e barato, então sobe.
        blocker = calculate_score(self.make_group("import_error", category="environmental"))
        self.assertEqual(unused.deadline_tier, 3)
        self.assertEqual(blocker.deadline_tier, 1)
        # o que importa e a posicao na fila, nao a faixa bruta de score: o
        # bloqueador vem antes mesmo quando o score bruto nao o favorece
        self.assertEqual(
            [item.concept for item in rank_groups([unused, blocker])],
            ["import_error", "unused_variable"],
        )
        self.assertEqual(blocker.priority, "high")
        self.assertEqual(unused.priority, "low")

    def test_dynamic_sql_scores_above_high_threshold(self):
        result = calculate_score(self.make_group("dynamic_sql"))
        self.assertGreater(result.score, 300)

    def test_missing_notes_are_neutral_and_zero_denominator_is_protected(self):
        result = calculate_score(self.make_group("unused_variable", category="code_quality"))
        notes = notes_for_group(self.make_group("unused_variable", category="code_quality"))
        # o atenuante "tempo" e o esforco do conceito elevado ao expoente do tier
        self.assertEqual(notes["tempo"], 0.5 ** EXPOENTE_ESFORCO_POR_TIER[3])
        self.assertEqual(result.esforco_pontos, 0.5)
        self.assertGreater(result.score, 0)
        with patch("scoring.PESOS_ATENUANTES", {"tempo": 0.0}):
            protected = calculate_score(
                self.make_group("unused_variable", category="code_quality")
            )
        self.assertGreater(protected.score, 0)

    def test_same_input_is_deterministic(self):
        group = self.make_group("dynamic_sql")
        self.assertEqual(calculate_score(group), calculate_score(group))

    def test_score_bands_follow_the_thresholds(self):
        # Testa a função de faixa direto: com o termo de esforço ativo nenhum
        # conceito real cai na janela 200-300, então usar conceitos aqui tornaria
        # o teste frágil sem testar nada a mais.
        self.assertEqual(_priority_for_score(LIMIAR_ALTO + 1), "alto")
        self.assertEqual(_priority_for_score(LIMIAR_MEDIO + 1), "medio")
        self.assertEqual(_priority_for_score(LIMIAR_MEDIO), "baixo")
        self.assertEqual(score_priority_label("alto"), "high")
        self.assertEqual(score_priority_label("medio"), "medium")
        self.assertEqual(score_priority_label("baixo"), "low")


class _ScoredBuilder:
    """Helper compartilhado. Nao e TestCase para os testes nao rodarem duas vezes."""

    def scored(self, concept, file_path, *, category=None, kind=FindingKind.FINDING,
               metric_value=None, severity=None):
        finding = Finding(
            source_tool="radon" if kind == FindingKind.METRIC else "bandit",
            rule_id="radon.cc" if kind == FindingKind.METRIC else "B608",
            category=category or "security",
            file_path=file_path,
            line=10,
            description=concept,
            kind=kind,
            metric_value=metric_value,
            severity=severity,
        )
        return calculate_score(
            classify_group(
                FindingGroup(
                    concept=concept,
                    representative_finding=finding,
                    evidences=[finding],
                )
            )
        )


class DeadlineDominanceTests(_ScoredBuilder, unittest.TestCase):
    """A regra central do time, testada diretamente.

    "Nenhum finding que nao bloqueie o release pode ser mais prioritario do que
    um que bloqueie" -- e, dentro do questionario, o mais barato primeiro.
    """

    def test_worst_blocker_beats_best_non_blocker(self):
        """O caso adversario: bloqueador com score baixo vs livre com score alto."""

        # severidades escolhidas de proposito para o bloqueador ficar com o
        # score mais BAIXO -- e o que torna o caso interessante
        blocker = self.scored(
            "inconsistent_returns", "app/routes/report_routes.py",
            category="reliability", severity="LOW",
        )
        free = self.scored(
            "missing_timeout", "outro/arquivo.py",
            category="availability", severity="HIGH",
        )

        # o bloqueador tem score MENOR -- e o que torna o caso interessante
        self.assertLess(blocker.score, free.score)
        self.assertEqual(blocker.deadline_tier, 1)
        self.assertEqual(free.deadline_tier, 3)

        ordered = rank_groups([free, blocker])
        self.assertEqual(ordered[0].concept, "inconsistent_returns")
        self.assertLess(ordered[0].score, ordered[1].score)

    def test_tier_order_holds_across_all_tiers(self):
        items = [
            self.scored("unused_variable", "outro/arquivo.py", category="code_quality"),
            self.scored("debug_enabled", "run.py"),
            self.scored("cyclomatic_complexity", "app/helpers/date_helper.py",
                        category="maintainability", kind=FindingKind.METRIC,
                        metric_value=29, severity="F"),
            self.scored("dynamic_sql", "app/routes/report_routes.py"),
        ]
        tiers = [item.deadline_tier for item in rank_groups(items)]
        self.assertEqual(tiers, [0, 1, 2, 3])

    def test_sql_injection_in_report_path_is_tier_0(self):
        result = self.scored("dynamic_sql", "/repos/python/app/routes/report_routes.py")
        self.assertEqual(result.deadline_tier, 0)
        self.assertEqual(result.priority, "critical")
        self.assertTrue(result.blocks_release)
        self.assertEqual(result.questionnaire_items, (1,))

    def test_tier_2_is_ordered_cheapest_first(self):
        """Itens de questionario fora do caminho do release, por esforco."""

        items = [
            self.scored("weak_password_hash", "app/models/user.py"),   # 3.0 pts
            self.scored("dynamic_sql", "app/models/customer.py"),      # 2.0 pts
            self.scored("debug_enabled", "run.py"),                    # 0.5 pt
            self.scored("hardcoded_secret", "sync_data.py"),           # 1.0 pt
        ]
        for item in items:
            self.assertEqual(item.deadline_tier, 2)
        self.assertEqual(
            [item.concept for item in rank_groups(items)],
            ["debug_enabled", "hardcoded_secret", "dynamic_sql", "weak_password_hash"],
        )
        esforcos = [item.esforco_pontos for item in rank_groups(items)]
        self.assertEqual(esforcos, sorted(esforcos))

    def test_effort_needs_an_exponent_not_a_constant_factor(self):
        """Documenta por que EXPOENTE_ESFORCO_POR_TIER e expoente e nao fator.

        Com expoente 0 o esforco deixa de influir e a ordem do tier muda. Um
        fator constante, por outro lado, escalaria todos os scores do tier
        igualmente e nao reordenaria nada -- e a armadilha que este desenho evita.
        """

        def ordem_do_tier_2():
            items = [
                self.scored("weak_password_hash", "app/models/user.py"),
                self.scored("dynamic_sql", "app/models/customer.py"),
                self.scored("debug_enabled", "run.py"),
                self.scored("hardcoded_secret", "sync_data.py"),
            ]
            return [item.concept for item in rank_groups(items)]

        com_expoente = ordem_do_tier_2()
        with patch.dict("scoring.EXPOENTE_ESFORCO_POR_TIER", {2: 0.0}):
            sem_esforco = ordem_do_tier_2()
        self.assertNotEqual(com_expoente, sem_esforco)
        self.assertEqual(com_expoente[0], "debug_enabled")


class RankDeterminismTests(_ScoredBuilder, unittest.TestCase):
    """Scoring nao deterministico e desclassificacao pelo briefing."""

    def base(self):
        return [
            self.scored("dynamic_sql", "app/routes/report_routes.py"),
            self.scored("debug_enabled", "run.py"),
            self.scored("unused_variable", "a/a.py", category="code_quality"),
            self.scored("todo_comment", "b/b.py", category="code_quality"),
            self.scored("shadowed_builtin", "c/c.py", category="code_quality"),
        ]

    def test_rank_is_independent_of_input_order(self):
        items = self.base()
        direta = [item.group_id for item in rank_groups(items)]
        inversa = [item.group_id for item in rank_groups(list(reversed(items)))]
        self.assertEqual(direta, inversa)

    def test_rank_is_idempotent(self):
        items = self.base()
        uma = [item.group_id for item in rank_groups(items)]
        duas = [item.group_id for item in rank_groups(rank_groups(items))]
        self.assertEqual(uma, duas)

    def test_colliding_scores_are_broken_by_group_id(self):
        """unused_variable, todo_comment e shadowed_builtin dao o MESMO score."""

        items = [
            self.scored("unused_variable", "a/a.py", category="code_quality"),
            self.scored("todo_comment", "b/b.py", category="code_quality"),
            self.scored("shadowed_builtin", "c/c.py", category="code_quality"),
        ]
        self.assertEqual(len({item.score for item in items}), 1)
        ordered = rank_groups(items)
        self.assertEqual(
            [item.group_id for item in ordered],
            sorted(item.group_id for item in items),
        )


class SeverityWeightTests(_ScoredBuilder, unittest.TestCase):
    """O peso de severidade nao pode desmontar a ordem por prazo/esforco."""

    def test_metric_weight_is_monotonic_in_complexity(self):
        """Mais complexo tem de pontuar mais.

        O rank do radon nao serve como severidade: a escala e invertida
        (A = simples, F = inalteravel sem reescrita). Usamos metric_value.
        """

        scores = [
            self.scored(
                "cyclomatic_complexity", "outro/arquivo.py",
                category="maintainability", kind=FindingKind.METRIC,
                metric_value=cc, severity=rank,
            ).score
            for cc, rank in [(3, "A"), (13, "C"), (18, "D"), (29, "F")]
        ]
        self.assertEqual(scores, sorted(scores))
        self.assertLess(scores[0], scores[-1])

    def test_severity_weight_is_applied_once_not_per_note(self):
        """Aplicado por nota, o peso vira peso**5 e engole o esforco.

        Com 5 notas, um peso de 0.3 por nota daria 0.00243 -- faixa de ~400x
        contra HIGH, o que passa por cima da faixa de esforco (~8x no tier 2) e
        destroi a ordenacao "mais barato primeiro".
        """

        alto = self.scored("hardcoded_secret", "sync_data.py", severity="HIGH")
        baixo = self.scored("hardcoded_secret", "sync_data.py", severity="LOW")
        razao = alto.score / baixo.score
        self.assertAlmostEqual(razao, 1.0 / 0.3, places=6)
        self.assertLess(razao, 5.0)  # se fosse por nota, seria ~400x

    def test_effort_still_wins_over_severity_inside_tier_2(self):
        """A regra do time sobrevive as severidades reais das ferramentas.

        bandit reporta B201 (debug) como HIGH, B105 (credencial) como LOW e
        B608 (SQL) como MEDIUM -- ou seja, a severidade empurra na direcao
        contraria ao esforco. O esforco tem de ganhar.
        """

        items = [
            self.scored("dynamic_sql", "app/models/customer.py", severity="MEDIUM"),
            self.scored("debug_enabled", "run.py", severity="HIGH"),
            self.scored("hardcoded_secret", "sync_data.py", severity="LOW"),
        ]
        for item in items:
            self.assertEqual(item.deadline_tier, 2)
        ordenado = rank_groups(items)
        self.assertEqual(
            [item.concept for item in ordenado],
            ["debug_enabled", "hardcoded_secret", "dynamic_sql"],
        )
        esforcos = [item.esforco_pontos for item in ordenado]
        self.assertEqual(esforcos, sorted(esforcos))

    def test_unknown_severity_is_neutral_not_punished(self):
        sem_sev = self.scored("hardcoded_secret", "sync_data.py", severity=None)
        self.assertEqual(sem_sev.factors["peso_severidade"], 0.6)


if __name__ == "__main__":
    unittest.main()
