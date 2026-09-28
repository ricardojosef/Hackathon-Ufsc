import unittest

from report import CONCEPT_GUIDANCE, render_json, render_markdown
from scoring import ScoredFindingGroup


class ReportTests(unittest.TestCase):
    def make_result(self, concept="dynamic_sql", *, priority="critical",
                    deadline_tier=0, blocks_release=True,
                    questionnaire_items=(1,), esforco_pontos=2.0, score=3456.0):
        return ScoredFindingGroup(
            group_id=f"{concept}@app.py:10",
            concept=concept,
            category="security",
            classification_priority="critical",
            priority=priority,
            deadline_tier=deadline_tier,
            blocks_release=blocks_release,
            questionnaire_items=questionnaire_items,
            esforco_pontos=esforco_pontos,
            deadline_rationale="Bloqueia o release de 14 dias e responde Q1.",
            score=score,
            score_priority="alto",
            score_priority_mapped="high",
            notes={"financeiro": 4.0},
            formula="deterministic",
            factors={"source_tools": ["bandit", "semgrep"], "evidence_count": 2},
        )

    def test_guidance_covers_required_concepts(self):
        required = {
            "dynamic_sql", "hardcoded_secret", "weak_password_hash",
            "missing_timeout", "broad_exception", "swallowed_exception",
            "inconsistent_returns", "import_error", "cyclomatic_complexity",
            "excessive_branches", "excessive_returns", "excessive_locals",
            "unused_variable", "shadowed_builtin", "unnecessary_else_after_return",
            "todo_comment",
        }
        self.assertTrue(required.issubset(CONCEPT_GUIDANCE))
        for guidance in CONCEPT_GUIDANCE.values():
            self.assertTrue(all(guidance[field] for field in ("description", "impact", "recommendation")))

    def test_json_preserves_scoring_fields_and_adds_guidance(self):
        result = self.make_result()
        payload = render_json([result])
        self.assertIn('"score": 3456.0', payload)
        self.assertIn('"score_priority_mapped": "high"', payload)
        self.assertIn('"description":', payload)
        self.assertIn('"recommendation":', payload)
        self.assertIn('"business_impact":', payload)
        self.assertIn('"technical_impact":', payload)
        # campos de prazo tem de sobreviver ate o JSON final
        self.assertIn('"priority": "critical"', payload)
        self.assertIn('"deadline_tier": 0', payload)
        self.assertIn('"blocks_release": true', payload)

    def test_markdown_has_business_sections_and_full_traceability(self):
        markdown = render_markdown([self.make_result()])
        for heading in (
            "## Resumo executivo", "## Principais problemas", "## Plano de ação",
            "## Origem das recomendações", "## Limitações", "## Grupos e evidências",
            "## Como interpretar o scoring",
            "## Regra de ordenação",
        ):
            self.assertIn(heading, markdown)
        self.assertIn("evidence_count", markdown)
        self.assertIn("bandit, semgrep", markdown)
        self.assertIn("Impacto de negócio", markdown)
        self.assertIn("| high |", markdown)
        self.assertIn("Prioridade V1", markdown)

    def test_markdown_orders_by_deadline_tier_not_by_score(self):
        """A regra do time, verificada no render: prazo manda, score so desempata."""

        blocker = self.make_result(
            "inconsistent_returns", priority="high", deadline_tier=1,
            blocks_release=True, questionnaire_items=(), esforco_pontos=2.0,
            score=10.0,
        )
        sem_prazo = self.make_result(
            "todo_comment", priority="low", deadline_tier=3, blocks_release=False,
            questionnaire_items=(), esforco_pontos=0.5, score=9999.0,
        )
        markdown = render_markdown([sem_prazo, blocker])
        # o bloqueador tem score 1000x menor e ainda assim vem antes
        self.assertLess(
            markdown.index("inconsistent_returns"), markdown.index("todo_comment")
        )
        self.assertNotIn("O que a IA sugeriu", markdown)


if __name__ == "__main__":
    unittest.main()