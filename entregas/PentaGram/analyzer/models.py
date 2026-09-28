"""Normalized data structures for static-analysis results."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FindingKind(str, Enum):
    """Distinguishes a concrete tool result from a metric observation."""

    FINDING = "finding"
    METRIC = "metric"


@dataclass
class Finding:
    """Language-independent representation of one normalized tool result.

    Tool-specific values such as Bandit's HIGH, Radon's rank D, or Pylint's
    warning are kept as strings in ``severity``. This model deliberately has
    no score or priority fields.
    """

    source_tool: str
    description: str
    category: str | None = None
    rule_id: str | None = None
    file_path: str | None = None
    line: int | None = None
    severity: str | None = None
    confidence: str | None = None
    kind: FindingKind = FindingKind.FINDING
    metric_value: int | float | None = None
    threshold: int | float | None = None
    raw_data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_tool.strip():
            raise ValueError("source_tool must not be empty")
        if not self.description.strip():
            raise ValueError("description must not be empty")
        if self.line is not None and self.line < 1:
            raise ValueError("line must be greater than zero")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of this result."""

        return {
            "source_tool": self.source_tool,
            "rule_id": self.rule_id,
            "category": self.category,
            "file_path": self.file_path,
            "line": self.line,
            "description": self.description,
            "severity": self.severity,
            "confidence": self.confidence,
            "kind": self.kind.value,
            "metric_value": self.metric_value,
            "threshold": self.threshold,
            "raw_data": self.raw_data,
        }
