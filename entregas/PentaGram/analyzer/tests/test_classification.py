import unittest

from classification import classify_group, classify_groups
from deduplication import FindingGroup
from models import Finding, FindingKind


class ClassificationTests(unittest.TestCase):
    def make_group(
        self,
        concept,
        *,
        source_tool="bandit",
        rule_id="B608",
        category="security",
        kind=FindingKind.FINDING,
        severity=None,
        line=10,
    ):
        finding = Finding(
            source_tool=source_tool,
            rule_id=rule_id,
            category=category,
            file_path="file.py",
            line=line,
            description=concept,
            severity=severity,
            kind=kind,
        )
        return FindingGroup(
            concept=concept,
            representative_finding=finding,
            evidences=[finding],
        )

    def test_security_rules(self):
        for concept in ("dynamic_sql", "hardcoded_secret", "weak_password_hash"):
            result = classify_group(self.make_group(concept))
            self.assertEqual(result.category, "security")

    def test_reliability_rules(self):
        for concept in ("swallowed_exception", "inconsistent_returns", "broad_exception"):
            result = classify_group(self.make_group(concept))
            self.assertEqual(result.category, "reliability")

    def test_availability_rules(self):
        for concept in ("missing_timeout",):
            result = classify_group(self.make_group(concept))
            self.assertEqual(result.category, "availability")
            self.assertEqual(result.priority, "high")

    def test_maintainability_rules(self):
        for concept in ("excessive_returns", "excessive_branches", "excessive_locals"):
            result = classify_group(self.make_group(concept))
            self.assertEqual(result.category, "maintainability")

    def test_code_quality_rules(self):
        for concept in ("unused_variable", "unnecessary_else_after_return", "todo_comment"):
            result = classify_group(self.make_group(concept))
            self.assertEqual(result.category, "code_quality")

    def test_import_error_is_environmental(self):
        group = self.make_group(
            "import_error",
            source_tool="pylint",
            rule_id="E0401",
            category="correctness",
        )
        result = classify_group(group)
        self.assertEqual(result.category, "environmental")

    def test_phpstan_dependency_result_can_be_environmental(self):
        group = self.make_group(
            "phpstan:class.notFound",
            source_tool="phpstan",
            rule_id="class.notFound",
            category="static_analysis",
        )
        result = classify_group(group)
        self.assertEqual(result.category, "environmental")
        self.assertIsNone(result.priority)

    def test_radon_below_threshold_remains_metric_only(self):
        group = self.make_group(
            "cyclomatic_complexity",
            source_tool="radon",
            rule_id="radon.cc",
            category="maintainability",
            kind=FindingKind.METRIC,
            severity="B",
        )
        result = classify_group(group)
        self.assertEqual(result.category, "maintainability")
        self.assertFalse(result.is_candidate)
        self.assertIsNone(result.priority)

    def test_radon_candidate_rank_is_maintainability(self):
        group = self.make_group(
            "cyclomatic_complexity",
            source_tool="radon",
            rule_id="radon.cc",
            category="maintainability",
            kind=FindingKind.METRIC,
            severity="D",
        )
        result = classify_group(group)
        self.assertEqual(result.category, "maintainability")
        self.assertTrue(result.is_candidate)
        self.assertEqual(result.priority, "medium")

    def test_phpmetrics_metric_is_not_automatically_critical(self):
        group = self.make_group(
            "phpmetrics:ccn",
            source_tool="phpmetrics",
            rule_id="ccn",
            category="maintainability",
            kind=FindingKind.METRIC,
            severity=None,
        )
        result = classify_group(group)
        self.assertFalse(result.is_candidate)
        self.assertIsNone(result.priority)
        self.assertNotEqual(result.priority, "critical")

    def test_classification_is_independent_of_group_order(self):
        groups = [
            self.make_group("dynamic_sql"),
            self.make_group("missing_timeout", rule_id="B113", category="security"),
            self.make_group("excessive_branches", rule_id="R0912", category="maintainability"),
        ]
        first = [
            (item.concept, item.category, item.priority)
            for item in classify_groups(groups)
        ]
        second = [
            (item.concept, item.category, item.priority)
            for item in classify_groups(list(reversed(groups)))
        ]
        self.assertEqual(sorted(first), sorted(second))


if __name__ == "__main__":
    unittest.main()
