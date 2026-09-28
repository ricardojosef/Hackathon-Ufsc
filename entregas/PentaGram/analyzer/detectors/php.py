"""Parsers for existing PHPStan and PHPMetrics JSON output."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from models import Finding, FindingKind


PHPSTAN_ENVIRONMENTAL_IDENTIFIERS = frozenset(
    {
        "class.notFound",
        "function.notFound",
        "method.notFound",
        "property.notFound",
        "trait.notFound",
    }
)


def parse_phpstan(data: Mapping[str, Any]) -> list[Finding]:
    """Convert PHPStan file messages into concrete normalized findings."""

    files = data.get("files")
    if not isinstance(files, Mapping):
        raise ValueError("PHPStan JSON must contain a 'files' object")

    findings: list[Finding] = []
    for file_path, file_data in files.items():
        if not isinstance(file_path, str) or not isinstance(file_data, Mapping):
            raise ValueError("PHPStan files must map paths to objects")
        messages = file_data.get("messages")
        if not isinstance(messages, list):
            raise ValueError(f"PHPStan file '{file_path}' must contain a messages list")
        for message in messages:
            if not isinstance(message, Mapping):
                raise ValueError("PHPStan messages must be objects")
            identifier = _required_string(message, "identifier", "PHPStan")
            description = _required_string(message, "message", "PHPStan")
            findings.append(
                Finding(
                    source_tool="phpstan",
                    rule_id=identifier,
                    category=(
                        "environmental"
                        if identifier in PHPSTAN_ENVIRONMENTAL_IDENTIFIERS
                        else "correctness"
                    ),
                    file_path=file_path,
                    line=_optional_int(message.get("line")),
                    description=description,
                    raw_data=dict(message),
                )
            )
    return findings


def parse_phpmetrics(data: Mapping[str, Any]) -> list[Finding]:
    """Convert class-level PHPMetrics CCN metrics into metric findings.

    Package, project, tree, and search aggregates have no concrete file/line
    occurrence in this JSON, so they are intentionally not emitted as debts.
    """

    findings: list[Finding] = []
    for entry_name, entry in data.items():
        if not isinstance(entry_name, str) or not isinstance(entry, Mapping):
            continue
        if entry.get("_type") != "Hal\\Metric\\ClassMetric":
            continue
        complexity = entry.get("ccn")
        if not _is_number(complexity):
            continue
        class_name = entry.get("name")
        if not isinstance(class_name, str) or not class_name.strip():
            class_name = entry_name
        findings.append(
            Finding(
                source_tool="phpmetrics",
                rule_id="ccn",
                category="maintainability",
                description=f"Cyclomatic complexity for PHP class {class_name}: {complexity}",
                kind=FindingKind.METRIC,
                metric_value=complexity,
                raw_data=dict(entry),
            )
        )
    return findings


def _required_string(
    value: Mapping[str, Any], field_name: str, tool_name: str
) -> str:
    item = value.get(field_name)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"{tool_name} result requires a non-empty '{field_name}'")
    return item


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)