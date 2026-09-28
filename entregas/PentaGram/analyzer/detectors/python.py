"""Parsers for Python static-analysis tool output."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from models import Finding, FindingKind


def load_json(path: str | Path) -> Any:
    """Load JSON from a file and expose clear parser-facing errors."""

    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Could not read JSON file '{path}': {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in '{path}': {exc}") from exc


def parse_bandit(data: Mapping[str, Any]) -> list[Finding]:
    """Convert Bandit's ``results`` entries into security findings."""

    results = _results_list(data, "Bandit", "results")
    findings: list[Finding] = []

    for result in results:
        findings.append(
            Finding(
                source_tool="bandit",
                rule_id=_optional_string(result, "test_id"),
                category="security",
                file_path=_optional_string(result, "filename"),
                line=_optional_int(result, "line_number"),
                description=_required_description(result, "issue_text", "Bandit"),
                severity=_optional_string(result, "issue_severity"),
                confidence=_optional_string(result, "issue_confidence"),
                raw_data=dict(result),
            )
        )

    return findings


def parse_semgrep(data: Mapping[str, Any]) -> list[Finding]:
    """Convert Semgrep's ``results`` entries into security findings."""

    results = _results_list(data, "Semgrep", "results")
    findings: list[Finding] = []

    for result in results:
        extra = _optional_mapping(result, "extra")
        start = _optional_mapping(result, "start")
        description = _required_nested_description(extra, "message", "Semgrep")

        findings.append(
            Finding(
                source_tool="semgrep",
                rule_id=_optional_string(result, "check_id"),
                category="security",
                file_path=_optional_string(result, "path"),
                line=_optional_int(start, "line"),
                description=description,
                severity=_optional_string(extra, "severity"),
                confidence=_optional_string(
                    _optional_mapping(extra, "metadata"), "confidence"
                ),
                raw_data=dict(result),
            )
        )

    return findings


def parse_pylint(data: Sequence[Mapping[str, Any]]) -> list[Finding]:
    """Convert Pylint messages into quality findings.

    Pylint's message type is preserved as ``severity``. The category mapping is
    intentionally small: errors describe correctness, while warnings,
    refactors, conventions, and informational messages describe maintainability.
    ``import-error`` is left for the classification layer to categorize,
    because this parser cannot prove whether the missing import is a real
    defect or an artifact of the analysis environment.
    """

    messages = _mapping_list(data, "Pylint")
    findings: list[Finding] = []

    for message in messages:
        rule_id = _optional_string(message, "message-id")
        symbol = _optional_string(message, "symbol")
        message_text = _required_description(message, "message", "Pylint")
        message_type = _optional_string(message, "type")

        findings.append(
            Finding(
                source_tool="pylint",
                rule_id=rule_id or symbol,
                category=_pylint_category(message_type),
                file_path=_optional_string(message, "path"),
                line=_optional_int(message, "line"),
                description=message_text,
                severity=message_type,
                raw_data=dict(message),
            )
        )

    return findings


def parse_radon(data: Mapping[str, Any]) -> list[Finding]:
    """Convert Radon CC's top-level entries into metric findings.

    Radon class entries may contain nested method data. Only top-level entries
    become objects here, preserving the JSON structure in ``raw_data`` and
    leaving aggregation or deduplication to a later stage.
    """

    if not isinstance(data, Mapping):
        raise ValueError("Radon JSON must be an object keyed by file path")

    findings: list[Finding] = []
    for file_path, entries in data.items():
        if not isinstance(file_path, str):
            raise ValueError("Radon file path keys must be strings")
        if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
            raise ValueError(f"Radon entries for '{file_path}' must be a list")

        for entry in entries:
            if not isinstance(entry, Mapping):
                raise ValueError(f"Radon entry for '{file_path}' must be an object")

            name = _optional_string(entry, "name") or "unnamed"
            complexity = _optional_number(entry, "complexity")
            rank = _optional_string(entry, "rank")
            description = f"Cyclomatic complexity for {name}"
            if complexity is not None:
                description += f": {complexity}"
            if rank:
                description += f" (rank {rank})"

            findings.append(
                Finding(
                    source_tool="radon",
                    rule_id="radon.cc",
                    category="maintainability",
                    file_path=file_path,
                    line=_optional_int(entry, "lineno"),
                    description=description,
                    severity=rank,
                    kind=FindingKind.METRIC,
                    metric_value=complexity,
                    threshold=None,
                    raw_data=dict(entry),
                )
            )

    return findings


def _results_list(
    data: Mapping[str, Any], tool_name: str, field_name: str
) -> list[Mapping[str, Any]]:
    if not isinstance(data, Mapping):
        raise ValueError(f"{tool_name} JSON must be an object")
    return _mapping_list(data.get(field_name), tool_name, field_name)


def _mapping_list(
    value: Any, tool_name: str, field_name: str = "results"
) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{tool_name} {field_name} must be a list of objects")
    if not all(isinstance(item, Mapping) for item in value):
        raise ValueError(f"{tool_name} {field_name} must contain only objects")
    return list(value)


def _optional_mapping(value: Mapping[str, Any], field_name: str) -> Mapping[str, Any]:
    nested = value.get(field_name)
    if nested is None:
        return {}
    if not isinstance(nested, Mapping):
        raise ValueError(f"Field '{field_name}' must be an object when present")
    return nested


def _optional_string(value: Mapping[str, Any], field_name: str) -> str | None:
    item = value.get(field_name)
    return item if isinstance(item, str) else None


def _optional_int(value: Mapping[str, Any], field_name: str) -> int | None:
    item = value.get(field_name)
    return item if isinstance(item, int) and not isinstance(item, bool) else None


def _optional_number(value: Mapping[str, Any], field_name: str) -> int | float | None:
    item = value.get(field_name)
    if isinstance(item, (int, float)) and not isinstance(item, bool):
        return item
    return None


def _required_description(
    value: Mapping[str, Any], field_name: str, tool_name: str
) -> str:
    description = _optional_string(value, field_name)
    if not description or not description.strip():
        raise ValueError(f"{tool_name} result requires a non-empty '{field_name}'")
    return description


def _required_nested_description(
    value: Mapping[str, Any], field_name: str, tool_name: str
) -> str:
    return _required_description(value, field_name, tool_name)


def _pylint_category(message_type: str | None) -> str:
    if message_type in {"error", "fatal"}:
        return "correctness"
    if message_type in {"warning", "refactor", "convention", "info"}:
        return "maintainability"
    return "quality"
