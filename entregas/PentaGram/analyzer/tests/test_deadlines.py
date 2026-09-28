import unittest

from deadlines import (
    NEVER_BLOCKS_RELEASE,
    QUESTIONNAIRE_CONCEPTS,
    TIER_RELEASE,
    TIER_RELEASE_E_QUESTIONARIO,
    TIER_QUESTIONARIO,
    TIER_SEM_PRAZO,
    blocks_release,
    deadline_tier,
    is_in_release_path,
    questionnaire_items,
    tier_label,
)


class ReleasePathTests(unittest.TestCase):
    """O casamento de path é o ponto de falha silenciosa desta feature.

    As ferramentas devolvem o path como foram invocadas: absoluto dentro do
    container, relativo se rodadas da raiz do alvo. Se o casamento exigisse
    igualdade, blocks_release() devolveria False para tudo sem erro nenhum.
    """

    def test_absolute_container_path_matches(self):
        self.assertTrue(
            is_in_release_path("/repos/python/app/routes/report_routes.py")
        )

    def test_relative_path_matches(self):
        self.assertTrue(is_in_release_path("app/routes/report_routes.py"))

    def test_windows_separators_match(self):
        self.assertTrue(is_in_release_path(r"repos\python\app\everything.py"))

    def test_every_declared_suffix_matches_both_forms(self):
        from deadlines import RELEASE_PATH_SUFFIXES

        for suffix in RELEASE_PATH_SUFFIXES:
            self.assertTrue(is_in_release_path(suffix), suffix)
            self.assertTrue(is_in_release_path(f"/repos/python/{suffix}"), suffix)

    def test_file_outside_report_path_does_not_match(self):
        self.assertFalse(is_in_release_path("app/models/customer.py"))
        self.assertFalse(is_in_release_path("run.py"))
        self.assertFalse(is_in_release_path("sync_data.py"))

    def test_partial_name_does_not_match(self):
        # "not_everything.py" não pode casar com "app/everything.py"
        self.assertFalse(is_in_release_path("app/not_everything.py"))

    def test_missing_path_does_not_match(self):
        self.assertFalse(is_in_release_path(None))
        self.assertFalse(is_in_release_path(""))


class QuestionnaireTests(unittest.TestCase):
    def test_each_concept_maps_to_its_questions(self):
        self.assertEqual(questionnaire_items("dynamic_sql"), (1,))
        self.assertEqual(questionnaire_items("weak_password_hash"), (3, 7))
        self.assertEqual(questionnaire_items("hardcoded_secret"), (4,))
        self.assertEqual(questionnaire_items("debug_enabled"), (6,))

    def test_unmapped_concept_has_no_questions(self):
        self.assertEqual(questionnaire_items("unused_variable"), ())

    def test_questions_are_within_the_questionnaire(self):
        # docs/security-questionnaire.md tem 7 perguntas
        for concept, items in QUESTIONNAIRE_CONCEPTS.items():
            for item in items:
                self.assertIn(item, range(1, 8), f"{concept} -> Q{item}")


class TierTests(unittest.TestCase):
    def test_tier_0_blocks_release_and_answers_questionnaire(self):
        # SQL injection dentro do caminho do relatório
        tier = deadline_tier("dynamic_sql", "app/routes/report_routes.py")
        self.assertEqual(tier, TIER_RELEASE_E_QUESTIONARIO)

    def test_tier_1_blocks_release_only(self):
        # complexidade no date_helper: caminho do relatório, fora do questionário
        tier = deadline_tier("cyclomatic_complexity", "app/helpers/date_helper.py")
        self.assertEqual(tier, TIER_RELEASE)

    def test_tier_2_questionnaire_only(self):
        # debug=True em run.py: Q6, fora do caminho do relatório
        self.assertEqual(deadline_tier("debug_enabled", "run.py"), TIER_QUESTIONARIO)
        # credencial em sync_data.py: Q4, fora do caminho
        self.assertEqual(
            deadline_tier("hardcoded_secret", "sync_data.py"), TIER_QUESTIONARIO
        )
        # SQL em models/customer.py: Q1, fora do caminho
        self.assertEqual(
            deadline_tier("dynamic_sql", "app/models/customer.py"), TIER_QUESTIONARIO
        )

    def test_tier_3_no_deadline(self):
        tier = deadline_tier("unused_variable", "app/models/customer.py")
        self.assertEqual(tier, TIER_SEM_PRAZO)

    def test_cosmetic_concepts_never_block_even_inside_the_release_path(self):
        """Um `# TODO` dentro de everything.py não segura uma entrega.

        everything.py é o monolito e está no caminho do relatório, então sem esta
        regra qualquer lint cosmético dele entraria no tier 1 e passaria na frente
        de vulnerabilidade real -- falso positivo, que o briefing desconta.
        """

        for concept in NEVER_BLOCKS_RELEASE:
            self.assertFalse(
                blocks_release(concept, "app/everything.py"), concept
            )
            self.assertEqual(
                deadline_tier(concept, "app/everything.py"), TIER_SEM_PRAZO, concept
            )

    def test_real_problem_in_the_same_file_still_blocks(self):
        # a exceção é por conceito, não por arquivo: o mesmo everything.py
        # continua bloqueando para os achados que importam
        self.assertTrue(blocks_release("dynamic_sql", "app/everything.py"))
        self.assertTrue(blocks_release("weak_password_hash", "app/everything.py"))
        self.assertEqual(
            deadline_tier("dynamic_sql", "app/everything.py"),
            TIER_RELEASE_E_QUESTIONARIO,
        )

    def test_cosmetic_concept_is_not_in_the_questionnaire(self):
        # garante que a exclusão não esconde item de questionário sem querer
        for concept in NEVER_BLOCKS_RELEASE:
            self.assertEqual(questionnaire_items(concept), (), concept)

    def test_correctness_concept_blocks_anywhere(self):
        # import_error bloqueia mesmo fora do caminho do relatório: sem staging
        # e com deploy = git pull, não sobe
        self.assertTrue(blocks_release("import_error", "app/models/customer.py"))
        self.assertEqual(
            deadline_tier("import_error", "app/models/customer.py"), TIER_RELEASE
        )


class TierLabelTests(unittest.TestCase):
    def test_labels_follow_the_tier(self):
        self.assertEqual(tier_label(TIER_RELEASE_E_QUESTIONARIO, 0.0, 300.0), "critical")
        self.assertEqual(tier_label(TIER_RELEASE, 0.0, 300.0), "high")
        self.assertEqual(tier_label(TIER_QUESTIONARIO, 0.0, 300.0), "medium")

    def test_tier_3_label_falls_back_to_score(self):
        self.assertEqual(tier_label(TIER_SEM_PRAZO, 583.2, 300.0), "medium")
        self.assertEqual(tier_label(TIER_SEM_PRAZO, 57.6, 300.0), "low")

    def test_tier_3_never_outranks_a_release_blocker_label(self):
        # mesmo com score altíssimo, tier 3 não chega a critical/high
        self.assertIn(tier_label(TIER_SEM_PRAZO, 10_000.0, 300.0), {"medium", "low"})


if __name__ == "__main__":
    unittest.main()
