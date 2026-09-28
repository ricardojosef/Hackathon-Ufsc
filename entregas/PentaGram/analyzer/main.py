"""Run the existing Python detector outputs through the full pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from classification import classify_groups
from deduplication import deduplicate_findings
from detectors.python import parse_bandit, parse_pylint, parse_radon, parse_semgrep
from detectors.php import parse_phpmetrics, parse_phpstan
from report import render_json, render_markdown
from scoring import score_groups
from ai_report import generate_ai_report


def load_findings(output_dir: Path):
    """Load normalized findings from detector JSONs without changing them."""

    findings = [
        *parse_bandit(_read_json(output_dir / "bandit.json")),
        *parse_semgrep(_read_json(output_dir / "semgrep-python.json")),
        *parse_pylint(_read_json(output_dir / "pylint.json")),
        *parse_radon(_read_json(output_dir / "radon-cc.json")),
    ]
    if (output_dir / "phpstan.json").exists():
        findings.extend(parse_phpstan(_read_json(output_dir / "phpstan.json")))
    if (output_dir / "phpmetrics.json").exists():
        findings.extend(parse_phpmetrics(_read_json(output_dir / "phpmetrics.json")))
    return findings


def run(output_dir: Path, report_dir: Path):
    findings = load_findings(output_dir)
    groups = deduplicate_findings(findings)
    classified = classify_groups(groups)
    scored = score_groups(classified)
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "report.json").write_text(render_json(scored), encoding="utf-8")
    (report_dir / "report.md").write_text(render_markdown(scored), encoding="utf-8")
    return findings, groups, classified, scored


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--report-dir", type=Path, default=Path("analyzer/output"))
    parser.add_argument("--ai-report", action="store_true")
    args = parser.parse_args()
    findings, groups, classified, scored = run(args.output_dir, args.report_dir)
    print(f"Findings: {len(findings)}")
    print(f"Groups: {len(groups)}")
    print(f"Classified: {len(classified)}")
    print(f"Scored: {len(scored)}")
    if args.ai_report:
        try:
            ai_path = generate_ai_report(
                args.report_dir / "report.json",
                args.report_dir / "ai_report.md",
            )
            print(f"AI report: {ai_path}")
        except Exception as exc:
            print(f"AI report unavailable: {exc}")


if __name__ == "__main__":
    main()