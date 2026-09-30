"""
Testes do scoring model.

Escritos em `unittest` (stdlib) e não em pytest de propósito: o ambiente de
avaliação pode não ter pytest instalado, e um teste que não roda não prova
nada. Rodam com `python -m unittest discover` ou com `pytest`, indiferente.

Cobrem as quatro propriedades que sustentam a entrega:
  1. determinismo          — mesma entrada, mesma saída, sempre
  2. independência do relógio — rodar amanhã não muda o resultado
  3. monotonicidade        — mais severo nunca pontua menos
  4. teto da penalidade    — esforço não zera um achado crítico
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from ..config import load_business_profile
from ..models import Category, Finding, Location, Priority, Severity, Window
from ..scoring import (
    BASE_BY_SEVERITY,
    EFFORT_PENALTY_CAP,
    THRESHOLD_ALTA,
    THRESHOLD_CRITICA,
    describe_model,
    score_all,
    score_finding,
)

PROFILE = load_business_profile()


def make_finding(
    *,
    rule_id: str = "SEC.SQLI",
    category: Category = Category.SECURITY,
    severity: Severity = Severity.CRITICAL,
    effort: float = 3.0,
    tags: set[str] | None = None,
    sources: tuple[str, ...] = ("native-ast",),
    locations: int = 1,
    file: str = "app/x.py",
) -> Finding:
    """Constrói um Finding sintético para os testes."""
    return Finding(
        rule_id=rule_id,
        category=category,
        name="Achado de teste",
        description="descrição",
        severity=severity,
        locations=tuple(
            Location(file=file, line=10 + i, evidence="ev") for i in range(locations)
        ),
        effort_points=effort,
        tags=frozenset(tags or set()),
        sources=sources,
        remediation="corrigir",
    )


class TestDeterminism(unittest.TestCase):
    """A propriedade que o briefing usa como critério de desclassificação."""

    def test_mesmo_input_mesmo_score(self):
        f = make_finding(tags={"multi-tenant", "questionario:q1"})
        primeiro = score_finding(f, PROFILE)
        for _ in range(50):
            self.assertEqual(score_finding(f, PROFILE).score, primeiro.score)

    def test_ordem_de_entrada_nao_afeta_resultado(self):
        """
        Embaralhar a lista de entrada não pode mudar os IDs atribuídos.

        Se a ordenação não fosse por chave total, achados de mesmo score
        trocariam de DT-NN conforme a ordem de descoberta no sistema de
        arquivos — que varia entre máquinas.
        """
        findings = [
            make_finding(rule_id="SEC.SQLI", file="a.py"),
            make_finding(rule_id="SEC.XSS", category=Category.SECURITY,
                         severity=Severity.HIGH, file="b.py"),
            make_finding(rule_id="PERF.NPLUS1", category=Category.PERFORMANCE,
                         severity=Severity.HIGH, file="c.py"),
            make_finding(rule_id="MAINT.DEAD_CODE", category=Category.MAINTAINABILITY,
                         severity=Severity.LOW, file="d.py"),
        ]
        esperado = [(s.id, s.finding.rule_id) for s in score_all(findings, PROFILE)]
        for shift in range(1, len(findings)):
            rotacionado = findings[shift:] + findings[:shift]
            obtido = [(s.id, s.finding.rule_id) for s in score_all(rotacionado, PROFILE)]
            self.assertEqual(obtido, esperado)

    def test_empate_de_score_desempatado_por_chave_estavel(self):
        """Dois achados idênticos em score recebem IDs por rule_id, não por sorte."""
        a = make_finding(rule_id="SEC.ZZZ", file="z.py")
        b = make_finding(rule_id="SEC.AAA", file="a.py")
        resultado = score_all([a, b], PROFILE)
        self.assertEqual(resultado[0].score, resultado[1].score)
        self.assertEqual(resultado[0].finding.rule_id, "SEC.AAA")

    def test_score_e_inteiro(self):
        """Float acumulado quebraria a reprodutibilidade entre plataformas."""
        for effort in (0.5, 1.0, 2.25, 3.75, 4.88, 13.0):
            s = score_finding(make_finding(effort=effort), PROFILE)
            self.assertIsInstance(s.score, int)


class TestIndependenciaDoRelogio(unittest.TestCase):
    """
    O erro mais comum neste desafio: calcular "faltam 14 dias" com o relógio.

    Os prazos vêm do business_profile como DIAS RESTANTES fixos. Estes testes
    garantem que nada no caminho do scoring lê a data do sistema.
    """

    def test_scoring_nao_le_o_relogio(self):
        """
        Varre a AST do módulo, não o texto.

        Buscar por string pegaria também a docstring que PROÍBE `datetime.now`,
        e a análise sintática responde a pergunta certa: existe alguma chamada
        real ao relógio no código executável?
        """
        import ast
        import inspect

        from .. import scoring

        tree = ast.parse(inspect.getsource(scoring))
        proibidos = {"now", "today", "time", "utcnow", "monotonic"}
        chamadas = [
            ast.unparse(node.func)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        ]
        for chamada in chamadas:
            alvo = chamada.rsplit(".", 1)[-1]
            self.assertNotIn(
                alvo, proibidos, f"scoring.py chama `{chamada}` — quebra o determinismo"
            )

        # Nem sequer importa os módulos de tempo.
        importados = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        } | {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        self.assertNotIn("datetime", importados)
        self.assertNotIn("time", importados)

    def test_prazos_vem_da_configuracao(self):
        self.assertEqual(PROFILE.release.get("dias_restantes"), 14)
        self.assertEqual(PROFILE.questionario_prazo.get("dias_restantes"), 30)


class TestMonotonicidade(unittest.TestCase):
    def test_severidade_maior_nunca_pontua_menos(self):
        anterior = -1
        for sev in (Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL):
            score = score_finding(make_finding(severity=sev, effort=1.0), PROFILE).score
            self.assertGreater(score, anterior, f"severidade {sev.label} quebrou a ordem")
            anterior = score

    def test_esforco_maior_nunca_pontua_mais(self):
        anterior = 10**9
        for effort in (1.0, 3.0, 5.0, 8.0, 13.0, 21.0):
            score = score_finding(make_finding(effort=effort), PROFILE).score
            self.assertLessEqual(score, anterior)
            anterior = score

    def test_mais_ocorrencias_nunca_reduz_prioridade(self):
        poucos = score_finding(make_finding(locations=1), PROFILE).score
        muitos = score_finding(make_finding(locations=6), PROFILE).score
        self.assertGreaterEqual(muitos, poucos)


class TestPenalidadeDeEsforco(unittest.TestCase):
    """A regra mais contestável do modelo — por isso a mais testada."""

    def test_teto_impede_que_esforco_zere_achado_critico(self):
        """SQL Injection continua Crítica mesmo custando 21 SP."""
        caro = make_finding(
            severity=Severity.CRITICAL,
            effort=21.0,
            tags={"questionario:q1", "multi-tenant"},
        )
        s = score_finding(caro, PROFILE)
        self.assertEqual(s.priority, Priority.CRITICAL)

    def test_penalidade_respeita_o_teto(self):
        s = score_finding(make_finding(effort=100.0), PROFILE)
        penalidades = [c for c in s.components if c.kind == "penalty"]
        self.assertEqual(len(penalidades), 1)
        self.assertAlmostEqual(abs(penalidades[0].value), float(EFFORT_PENALTY_CAP))

    def test_esforco_pequeno_nao_tem_penalidade(self):
        for effort in (0.5, 1.0, 2.0, 3.0):
            s = score_finding(make_finding(effort=effort), PROFILE)
            self.assertEqual([c for c in s.components if c.kind == "penalty"], [])


class TestRegrasDeContexto(unittest.TestCase):
    """Cada multiplicador precisa ser rastreável ao business-context."""

    def test_questionario_eleva_achado_de_seguranca(self):
        base = score_finding(make_finding(), PROFILE).score
        com_q = score_finding(make_finding(tags={"questionario:q1"}), PROFILE).score
        self.assertGreater(com_q, base)

    def test_questionario_nao_se_aplica_fora_de_seguranca(self):
        """
        Um achado de Manutenibilidade com tag de questionário não deve ser
        inflado: o multiplicador existe porque o cliente pergunta sobre
        SEGURANÇA, não porque a tag está presente.
        """
        sem = score_finding(
            make_finding(category=Category.MAINTAINABILITY, severity=Severity.HIGH),
            PROFILE,
        )
        com = score_finding(
            make_finding(
                category=Category.MAINTAINABILITY,
                severity=Severity.HIGH,
                tags={"questionario:q1"},
            ),
            PROFILE,
        )
        self.assertEqual(sem.score, com.score)

    def test_corroboracao_aumenta_o_score(self):
        uma = score_finding(make_finding(sources=("native-ast",)), PROFILE).score
        duas = score_finding(make_finding(sources=("native-ast", "bandit")), PROFILE).score
        self.assertGreater(duas, uma)

    def test_achado_nao_corroboravel_nao_leva_desconto(self):
        """
        Ausência de testes não é reportada por linter nenhum. Penalizá-la por
        falta de corroboração seria puni-la por uma evidência impossível.
        """
        from ..models import NON_CORROBORABLE_RULES

        self.assertIn("ARCH.NO_TESTS", NON_CORROBORABLE_RULES)
        s = score_finding(
            make_finding(
                rule_id="ARCH.NO_TESTS",
                category=Category.ARCHITECTURE,
                severity=Severity.HIGH,
                effort=8.0,
                sources=("native-ast",),
            ),
            PROFILE,
        )
        descontos = [c for c in s.components if c.rule == "fonte_unica_nao_seguranca"]
        self.assertEqual(descontos, [])

    def test_multi_tenant_amplifica(self):
        base = score_finding(make_finding(), PROFILE).score
        mt = score_finding(make_finding(tags={"multi-tenant"}), PROFILE).score
        self.assertGreater(mt, base)

    def test_bus_factor_e_aditivo(self):
        base = score_finding(make_finding(), PROFILE).score
        bf = score_finding(make_finding(tags={"bus-factor"}), PROFILE).score
        self.assertEqual(bf - base, 25)

    def test_componentes_tem_justificativa(self):
        """Score sem explicação é número mágico; o briefing exige o contrário."""
        s = score_finding(
            make_finding(tags={"questionario:q1", "multi-tenant", "bus-factor", "data-loss"},
                         effort=8.0, locations=5),
            PROFILE,
        )
        self.assertGreaterEqual(len(s.components), 5)
        for c in s.components:
            self.assertTrue(c.rationale.strip(), f"componente {c.rule} sem justificativa")
            self.assertTrue(c.rule.strip())


class TestJanelas(unittest.TestCase):
    """O segundo eixo — responde 'o que faria primeiro'."""

    def test_item_barato_e_relevante_entra_antes_da_release(self):
        """
        Caso real do alvo: `debug=True` em produção — 0.5 SP, responde à
        pergunta 6 do questionário. Barato e relevante, entra na Onda 1.
        """
        s = score_finding(
            make_finding(
                rule_id="SEC.DEBUG_ON",
                severity=Severity.HIGH,
                effort=0.5,
                tags={"pii", "questionario:q6"},
            ),
            PROFILE,
        )
        self.assertGreaterEqual(s.score, THRESHOLD_ALTA)
        self.assertEqual(s.window, Window.PRE_RELEASE)

    def test_item_relevante_mas_caro_nao_entra_na_onda_1(self):
        """O orçamento até a release é de ~12 SP: 8 SP de um item só não cabe."""
        s = score_finding(
            make_finding(
                rule_id="SEC.NO_AUTHZ",
                severity=Severity.CRITICAL,
                effort=8.0,
                tags={"auth", "multi-tenant"},
            ),
            PROFILE,
        )
        self.assertGreaterEqual(s.score, THRESHOLD_ALTA)
        self.assertNotEqual(s.window, Window.PRE_RELEASE)

    def test_item_critico_e_caro_vai_para_o_sprint_de_seguranca(self):
        s = score_finding(
            make_finding(effort=14.0, tags={"questionario:q1", "multi-tenant"}), PROFILE
        )
        self.assertEqual(s.priority, Priority.CRITICAL)
        self.assertEqual(s.window, Window.SECURITY_SPRINT)

    def test_item_caro_e_pouco_relevante_fica_para_depois(self):
        s = score_finding(
            make_finding(
                rule_id="ARCH.GOD_MODULE",
                category=Category.ARCHITECTURE,
                severity=Severity.MEDIUM,
                effort=13.0,
            ),
            PROFILE,
        )
        self.assertEqual(s.window, Window.POST_RELEASE)

    def test_prioridade_e_janela_sao_independentes(self):
        """
        Um item pode ser Crítico E não caber antes da release. Se todo Crítico
        caísse em pre-release, o segundo eixo não estaria informando nada.
        """
        critico_caro = score_finding(
            make_finding(effort=14.0, tags={"questionario:q1", "multi-tenant"}), PROFILE
        )
        self.assertEqual(critico_caro.priority, Priority.CRITICAL)
        self.assertNotEqual(critico_caro.window, Window.PRE_RELEASE)


class TestIdsEOrdenacao(unittest.TestCase):
    def test_ids_sequenciais_e_ordenados_por_score(self):
        findings = [
            make_finding(rule_id=f"R{i}", severity=sev, file=f"f{i}.py")
            for i, sev in enumerate(
                [Severity.LOW, Severity.CRITICAL, Severity.MEDIUM, Severity.HIGH]
            )
        ]
        scored = score_all(findings, PROFILE)
        self.assertEqual([s.id for s in scored], ["DT-01", "DT-02", "DT-03", "DT-04"])
        scores = [s.score for s in scored]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_largura_do_id_acompanha_o_total(self):
        muitos = [make_finding(rule_id=f"R{i:03d}", file=f"f{i}.py") for i in range(120)]
        scored = score_all(muitos, PROFILE)
        self.assertEqual(scored[0].id, "DT-001")
        self.assertEqual(scored[-1].id, "DT-120")


class TestDescricaoDoModelo(unittest.TestCase):
    """`describe_model()` alimenta o relatório — precisa refletir o código."""

    def test_descricao_usa_as_constantes_reais(self):
        model = describe_model()
        self.assertTrue(model["deterministic"])
        self.assertFalse(model["uses_llm_for_priority"])
        self.assertEqual(model["thresholds"]["Crítica"], THRESHOLD_CRITICA)
        self.assertEqual(model["base_by_severity"]["Crítica"],
                         BASE_BY_SEVERITY[Severity.CRITICAL])

    def test_toda_regra_tem_justificativa_de_negocio(self):
        for rule in describe_model()["rules"]:
            self.assertTrue(rule["rationale"].strip())
            self.assertTrue(rule["effect"].strip())


if __name__ == "__main__":
    unittest.main()
