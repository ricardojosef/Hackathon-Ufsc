"""Deterministic concept normalization and Finding grouping."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from concepts import CATEGORY_COMPATIBILITY, concept_for_finding
from models import Finding, FindingKind


@dataclass
class FindingGroup:
    """A candidate debt with all original tool results retained as evidence."""

    concept: str
    representative_finding: Finding
    evidences: list[Finding]

    @property
    def source_tools(self) -> list[str]:
        return sorted({evidence.source_tool for evidence in self.evidences})

    @property
    def rule_ids(self) -> list[str]:
        return sorted(
            {evidence.rule_id for evidence in self.evidences if evidence.rule_id}
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept": self.concept,
            "representative_finding": self.representative_finding.to_dict(),
            "evidences": [evidence.to_dict() for evidence in self.evidences],
            "source_tools": self.source_tools,
            "rule_ids": self.rule_ids,
        }


def normalize_concepts(findings: list[Finding]) -> list[tuple[str, Finding]]:
    """Attach deterministic concepts without changing the Finding model."""

    return [(concept_for_finding(finding), finding) for finding in findings]


def deduplicate_findings(findings: list[Finding]) -> list[FindingGroup]:
    """Group equivalent concrete findings conservatively.

    Findings are grouped only when kind, category, concept, overlapping
    locations, and available evidence are compatible. Metrics remain separate
    because Radon's class/function/method levels are intentionally not merged.
    """

    normalized = sorted(
        normalize_concepts(findings),
        key=_finding_sort_key,
    )
    groups: list[FindingGroup] = []
    for concept, finding in normalized:
        matching_group = next(
            (
                group
                for group in groups
                if _can_join(group, concept, finding)
            ),
            None,
        )
        if matching_group is None:
            groups.append(
                FindingGroup(
                    concept=concept,
                    representative_finding=finding,
                    evidences=[finding],
                )
            )
        else:
            matching_group.evidences.append(finding)
    return groups


def _can_join(group: FindingGroup, concept: str, finding: Finding) -> bool:
    representative = group.representative_finding
    if concept != group.concept:
        return False
    if finding.kind != representative.kind:
        return False
    if not _categories_compatible(
        representative.category, finding.category, concept
    ):
        return False
    if finding.kind == FindingKind.METRIC:
        return False
    if not _locations_overlap(representative, finding):
        return False
    return _evidence_compatible(representative, finding)


def _locations_overlap(left: Finding, right: Finding) -> bool:
    if left.file_path is None or right.file_path is None:
        return False
    if left.file_path != right.file_path:
        return False
    if left.line is None or right.line is None:
        return False
    # A broad Semgrep flow can span multiple independent SQL statements. The
    # start line is the conservative occurrence anchor for cross-tool groups.
    return left.line == right.line


def _categories_compatible(
    left: str | None, right: str | None, concept: str
) -> bool:
    if left == right:
        return True
    if left is None or right is None:
        return False
    return frozenset({left, right}) in CATEGORY_COMPATIBILITY.get(concept, set())


def _finding_sort_key(item: tuple[str, Finding]) -> tuple[str, ...]:
    concept, finding = item
    return (
        finding.kind.value,
        finding.file_path or "",
        str(finding.line or 0),
        concept,
        finding.source_tool,
        finding.rule_id or "",
        finding.description,
        json.dumps(finding.raw_data, sort_keys=True, default=str),
    )


def _evidence_compatible(left: Finding, right: Finding) -> bool:
    left_texts = _evidence_texts(left)
    right_texts = _evidence_texts(right)
    if not left_texts or not right_texts:
        return True
    return any(
        _text_overlaps(left_text, right_text)
        for left_text in left_texts
        for right_text in right_texts
    )


def _evidence_texts(finding: Finding) -> list[str]:
    raw = finding.raw_data
    values: list[str] = []
    for value in (raw.get("code"),):
        if isinstance(value, str) and value.strip():
            values.append(value)

    extra = raw.get("extra")
    if isinstance(extra, dict):
        for key in ("lines",):
            value = extra.get(key)
            if isinstance(value, str) and value.strip():
                values.append(value)
    return values


def _text_overlaps(left: str, right: str) -> bool:
    left_lines = _evidence_lines(left)
    right_lines = _evidence_lines(right)
    if not left_lines or not right_lines:
        return True
    return any(
        line in other or other in line
        for line in left_lines
        for other in right_lines
    )


def _evidence_lines(value: str) -> list[str]:
    return [
        normalized
        for normalized in (_normalize_text(line) for line in value.splitlines())
        if normalized
    ]


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()
