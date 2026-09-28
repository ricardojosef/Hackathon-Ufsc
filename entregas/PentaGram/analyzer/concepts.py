"""Explicit, deterministic mappings from tool rules to technical concepts."""

from models import Finding


RULE_CONCEPTS: dict[tuple[str, str], str] = {
    ("bandit", "B105"): "hardcoded_secret",
    ("bandit", "B201"): "debug_enabled",
    ("bandit", "B110"): "swallowed_exception",
    ("bandit", "B113"): "missing_timeout",
    ("bandit", "B324"): "weak_password_hash",
    ("bandit", "B608"): "dynamic_sql",
    ("pylint", "E0401"): "import_error",
    ("pylint", "R0911"): "excessive_returns",
    ("pylint", "R0912"): "excessive_branches",
    ("pylint", "R0914"): "excessive_locals",
    ("pylint", "R1705"): "unnecessary_else_after_return",
    ("pylint", "R1710"): "inconsistent_returns",
    ("pylint", "W0511"): "todo_comment",
    ("pylint", "W0612"): "unused_variable",
    ("pylint", "W0622"): "shadowed_builtin",
    ("pylint", "W0718"): "broad_exception",
    ("pylint", "W3101"): "missing_timeout",
    ("radon", "radon.cc"): "cyclomatic_complexity",
    (
        "semgrep",
        "python.lang.security.audit.md5-used-as-password.md5-used-as-password",
    ): "weak_password_hash",
    (
        "semgrep",
        "python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query",
    ): "dynamic_sql",
    (
        "semgrep",
        "python.flask.security.injection.tainted-sql-string.tainted-sql-string",
    ): "dynamic_sql",
    (
        "semgrep",
        "python.django.security.injection.sql.sql-injection-using-db-cursor-execute.sql-injection-db-cursor-execute",
    ): "dynamic_sql",
    (
        "semgrep",
        "python.django.security.injection.tainted-sql-string.tainted-sql-string",
    ): "dynamic_sql",
    (
        "semgrep",
        "python.lang.security.audit.formatted-sql-query.formatted-sql-query",
    ): "dynamic_sql",
}


CATEGORY_COMPATIBILITY: dict[str, set[frozenset[str]]] = {
    "missing_timeout": {
        frozenset({"security", "maintainability"}),
    },
}


def concept_for_finding(finding: Finding) -> str:
    """Return the explicit concept or a stable source/rule fallback."""

    if finding.rule_id is not None:
        mapped = RULE_CONCEPTS.get((finding.source_tool, finding.rule_id))
        if mapped is not None:
            return mapped
        return f"{finding.source_tool}:{finding.rule_id}"
    return f"{finding.source_tool}:unknown"
