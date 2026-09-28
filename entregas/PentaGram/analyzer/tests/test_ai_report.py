import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ai_report import _build_prompt, _prompt_report, generate_ai_report


class AiReportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.report_path = self.root / "report.json"
        self.output_path = self.root / "ai_report.md"
        self.report = {
            "summary": {"scored_groups": 1, "high": 1, "medium": 0, "low": 0},
            "results": [
                {
                    "group_id": "dynamic_sql@app.py:10",
                    "concept": "dynamic_sql",
                    "category": "security",
                    "classification_priority": "critical",
                    "score": 3456.0,
                    "score_priority": "alto",
                    "score_priority_mapped": "high",
                    "factors": {"source_tools": ["bandit", "semgrep"]},
                }
            ],
        }
        self.report_path.write_text(json.dumps(self.report), encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_successful_generation_writes_markdown(self):
        fake_client = SimpleNamespace(
            models=SimpleNamespace(
                generate_content=lambda **kwargs: SimpleNamespace(text="# Gemini")
            )
        )
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), patch(
            "ai_report.genai.Client", return_value=fake_client
        ) as client:
            result = generate_ai_report(self.report_path, self.output_path)
        self.assertEqual(result, self.output_path)
        self.assertEqual(self.output_path.read_text(encoding="utf-8"), "# Gemini\n")
        client.assert_called_once_with(api_key="test-key")

    def test_missing_api_key_does_not_write_ai_report(self):
        with patch.dict(os.environ, {}, clear=True), patch("ai_report.load_dotenv"):
            with self.assertRaisesRegex(RuntimeError, "GEMINI_API_KEY"):
                generate_ai_report(self.report_path, self.output_path)
        self.assertFalse(self.output_path.exists())

    def test_api_error_is_propagated_for_cli_to_handle(self):
        fake_client = SimpleNamespace(
            models=SimpleNamespace(
                generate_content=lambda **kwargs: (_ for _ in ()).throw(
                    RuntimeError("service unavailable")
                )
            )
        )
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), patch(
            "ai_report.genai.Client", return_value=fake_client
        ):
            with self.assertRaisesRegex(RuntimeError, "service unavailable"):
                generate_ai_report(self.report_path, self.output_path)
        self.assertFalse(self.output_path.exists())

    def test_report_json_is_not_changed(self):
        original = self.report_path.read_bytes()
        fake_client = SimpleNamespace(
            models=SimpleNamespace(
                generate_content=lambda **kwargs: SimpleNamespace(text="ok")
            )
        )
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), patch(
            "ai_report.genai.Client", return_value=fake_client
        ):
            generate_ai_report(self.report_path, self.output_path)
        self.assertEqual(self.report_path.read_bytes(), original)

    def test_prompt_uses_only_current_deterministic_fields(self):
        prompt = _build_prompt(self.report)
        self.assertIn("score_priority_mapped", prompt)
        self.assertIn("source_tools", prompt)
        self.assertNotIn("validation_status", prompt)
        self.assertNotIn("status de validação", prompt)
        self.assertNotIn("DEFAULT_PASSWORD", prompt)

    def test_prompt_drops_repeated_scoring_details(self):
        report = {
            **self.report,
            "results": [
                {
                    **self.report["results"][0],
                    "notes": {"financeiro": 4.0},
                    "formula": "private formula",
                    "factors": {
                        "source_tools": ["bandit"],
                        "evidence_count": 2,
                        "aggravating_weights": {"seguranca": 2.5},
                    },
                }
            ],
        }
        projected = _prompt_report(report)
        self.assertNotIn("notes", projected["results"][0])
        self.assertNotIn("formula", projected["results"][0])
        self.assertNotIn("aggravating_weights", projected["results"][0])
        self.assertIn("source_tools", projected["results"][0])


if __name__ == "__main__":
    unittest.main()