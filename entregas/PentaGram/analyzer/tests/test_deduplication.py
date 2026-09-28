import unittest

from deduplication import deduplicate_findings
from models import Finding, FindingKind


class DeduplicationTests(unittest.TestCase):
    def test_bandit_and_semgrep_md5_are_grouped(self):
        findings = [
            Finding(
                source_tool="bandit",
                rule_id="B324",
                category="security",
                file_path="/repos/python/app/everything.py",
                line=168,
                description="Use of weak MD5 hash for security.",
                raw_data={"code": "hashlib.md5(password.encode()).hexdigest()"},
            ),
            Finding(
                source_tool="semgrep",
                rule_id=(
                    "python.lang.security.audit.md5-used-as-password."
                    "md5-used-as-password"
                ),
                category="security",
                file_path="/repos/python/app/everything.py",
                line=168,
                description="MD5 is used as a password hash.",
                raw_data={"extra": {"lines": "hashlib.md5(password.encode()).hexdigest()"}},
            ),
        ]
        groups = deduplicate_findings(findings)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].concept, "weak_password_hash")
        self.assertEqual(groups[0].source_tools, ["bandit", "semgrep"])

    def test_bandit_and_pylint_timeout_are_grouped(self):
        findings = [
            Finding(
                source_tool="bandit",
                rule_id="B113",
                category="security",
                file_path="/repos/python/app/services/notification_service.py",
                line=44,
                description="Requests call without timeout",
                raw_data={"code": "requests.post(url, json=data)"},
            ),
            Finding(
                source_tool="pylint",
                rule_id="W3101",
                category="maintainability",
                file_path="/repos/python/app/services/notification_service.py",
                line=44,
                description="Missing timeout argument for requests.post",
            ),
        ]
        groups = deduplicate_findings(findings)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].concept, "missing_timeout")

    def test_timeout_requires_compatible_category(self):
        findings = [
            Finding(
                source_tool="bandit",
                rule_id="B113",
                category="reliability",
                file_path="/repos/python/app/services/notification_service.py",
                line=44,
                description="Requests call without timeout",
            ),
            Finding(
                source_tool="pylint",
                rule_id="W3101",
                category="reliability",
                file_path="/repos/python/app/services/notification_service.py",
                line=44,
                description="Missing timeout argument",
            ),
        ]
        self.assertEqual(len(deduplicate_findings(findings)), 1)

    def test_pylint_returns_and_branches_stay_separate(self):
        findings = [
            Finding(
                source_tool="pylint",
                rule_id="R0911",
                category="maintainability",
                file_path="/repos/python/app/helpers/date_helper.py",
                line=8,
                description="Too many return statements",
            ),
            Finding(
                source_tool="pylint",
                rule_id="R0912",
                category="maintainability",
                file_path="/repos/python/app/helpers/date_helper.py",
                line=8,
                description="Too many branches",
            ),
        ]
        groups = deduplicate_findings(findings)
        self.assertEqual(len(groups), 2)
        self.assertEqual({group.concept for group in groups},
                         {"excessive_returns", "excessive_branches"})

    def test_unknown_rule_gets_stable_fallback(self):
        finding = Finding(
            source_tool="bandit",
            rule_id="B999",
            category="security",
            file_path="file.py",
            line=1,
            description="Unknown rule",
        )
        group = deduplicate_findings([finding])[0]
        self.assertEqual(group.concept, "bandit:B999")

    def test_evidence_is_preserved_conservatively(self):
        findings = [
            Finding(
                source_tool="bandit",
                rule_id="B324",
                category="security",
                file_path="file.py",
                line=10,
                description="MD5",
                raw_data={"code": "hashlib.md5(password)"},
            ),
            Finding(
                source_tool="semgrep",
                rule_id=(
                    "python.lang.security.audit.md5-used-as-password."
                    "md5-used-as-password"
                ),
                category="security",
                file_path="file.py",
                line=10,
                description="MD5 password hash",
                raw_data={"extra": {"lines": "hashlib.md5(password)"}},
            ),
        ]
        group = deduplicate_findings(findings)[0]
        self.assertEqual(len(group.evidences), 2)
        self.assertEqual(group.evidences[0].raw_data["code"], "hashlib.md5(password)")

    def test_metrics_are_not_grouped(self):
        findings = [
            Finding(
                source_tool="radon",
                rule_id="radon.cc",
                category="maintainability",
                file_path="file.py",
                line=10,
                description="complexity",
                kind=FindingKind.METRIC,
                metric_value=12,
            ),
            Finding(
                source_tool="radon",
                rule_id="radon.cc",
                category="maintainability",
                file_path="file.py",
                line=10,
                description="complexity duplicate level",
                kind=FindingKind.METRIC,
                metric_value=12,
            ),
        ]
        self.assertEqual(len(deduplicate_findings(findings)), 2)

    def test_deduplication_is_independent_of_input_order(self):
        findings = [
            Finding(
                source_tool="semgrep",
                rule_id=(
                    "python.lang.security.audit.md5-used-as-password."
                    "md5-used-as-password"
                ),
                category="security",
                file_path="file.py",
                line=10,
                description="MD5 password hash",
                raw_data={"extra": {"lines": "hashlib.md5(password)"}},
            ),
            Finding(
                source_tool="bandit",
                rule_id="B324",
                category="security",
                file_path="file.py",
                line=10,
                description="MD5",
                raw_data={"code": "hashlib.md5(password)"},
            ),
            Finding(
                source_tool="pylint",
                rule_id="R0911",
                category="maintainability",
                file_path="file.py",
                line=8,
                description="Too many return statements",
            ),
        ]

        def signature(items):
            return [
                (
                    group.concept,
                    sorted(group.source_tools),
                    sorted(group.rule_ids),
                    sorted(
                        (e.source_tool, e.rule_id, e.description)
                        for e in group.evidences
                    ),
                )
                for group in items
            ]

        first = signature(deduplicate_findings(findings))
        second = signature(deduplicate_findings(list(reversed(findings))))
        self.assertEqual(first, second)

    def test_different_generic_evidence_is_not_grouped_by_db_execute(self):
        findings = [
            Finding(
                source_tool="semgrep",
                rule_id="rule-a",
                category="security",
                file_path="file.py",
                line=20,
                description="First SQL evidence",
                raw_data={"extra": {"lines": "db.execute(query_one)"}},
            ),
            Finding(
                source_tool="semgrep",
                rule_id="rule-b",
                category="security",
                file_path="file.py",
                line=20,
                description="Second SQL evidence",
                raw_data={"extra": {"lines": "db.execute(query_two)"}},
            ),
        ]
        self.assertEqual(len(deduplicate_findings(findings)), 2)


if __name__ == "__main__":
    unittest.main()
