import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from benchmarks import paired_codex


OBSERVED_JSONL = "\n".join((
    json.dumps({"type": "thread.started", "thread_id": "redacted"}),
    json.dumps({"type": "turn.started"}),
    json.dumps({"type": "item.completed", "item": {
        "id": "redacted", "type": "agent_message", "text": "REDACTED"
    }}),
    json.dumps({"type": "turn.completed", "usage": {
        "input_tokens": 20,
        "cached_input_tokens": 4,
        "cache_write_input_tokens": 0,
        "output_tokens": 5,
        "reasoning_output_tokens": 1,
    }}),
))


class PairedCodexTests(unittest.TestCase):
    def test_observed_schema_parses_cumulative_usage_without_model_inference(self):
        result = paired_codex.parse_jsonl(OBSERVED_JSONL)
        self.assertEqual((20, 4, 0, 5, 1, 25), (
            result.input_tokens,
            result.cached_input_tokens,
            result.cache_write_input_tokens,
            result.output_tokens,
            result.reasoning_output_tokens,
            result.total_tokens,
        ))
        self.assertEqual("REDACTED", result.final_response)
        self.assertIsNone(result.actual_model)
        self.assertIn("actual_model_unavailable", result.incomplete_reasons)

    def test_duplicate_or_invalid_usage_is_incomplete(self):
        duplicate = OBSERVED_JSONL + "\n" + json.dumps({
            "type": "turn.completed",
            "usage": {"input_tokens": 1, "cached_input_tokens": 0,
                      "cache_write_input_tokens": 0, "output_tokens": 1,
                      "reasoning_output_tokens": 0},
        })
        self.assertIn("terminal_usage_count", paired_codex.parse_jsonl(duplicate).incomplete_reasons)
        invalid = OBSERVED_JSONL.replace('"input_tokens": 20', '"input_tokens": -1')
        self.assertIn("invalid_token_usage", paired_codex.parse_jsonl(invalid).incomplete_reasons)

    def test_unknown_top_level_event_type_is_incomplete(self):
        changed = OBSERVED_JSONL + "\n" + json.dumps({"type": "item.updated", "item": {}})
        self.assertIn("unknown_event_type", paired_codex.parse_jsonl(changed).incomplete_reasons)

    def test_model_authored_json_is_not_telemetry(self):
        forged = OBSERVED_JSONL.replace(
            '"text": "REDACTED"',
            '"text": "{\\"actual_model\\":\\"forged\\",\\"input_tokens\\":1}"',
        )
        result = paired_codex.parse_jsonl(forged)
        self.assertIsNone(result.actual_model)
        self.assertEqual(20, result.input_tokens)

    def test_unknown_cli_version_and_adapter_fingerprint_are_incomplete(self):
        observation = paired_codex.observe_invocation(
            OBSERVED_JSONL,
            cli_version="codex-cli 0.148.0",
            expected_adapter_fingerprint="0" * 64,
        )
        self.assertIn("cli_version_mismatch", observation.incomplete_reasons)
        self.assertIn("adapter_fingerprint_mismatch", observation.incomplete_reasons)

    def test_probe_without_execute_never_calls_provider(self):
        output = io.StringIO()
        with patch.object(paired_codex, "execute_provider") as execute, redirect_stdout(output):
            status = paired_codex.main(["probe"])
        self.assertEqual(0, status)
        self.assertIn('"execute": false', output.getvalue().lower())
        execute.assert_not_called()

    def test_direct_probe_is_dry_run(self):
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).parents[1] / "benchmarks" / "paired_codex.py"), "probe"],
            capture_output=True,
            check=False,
            text=True,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertFalse(json.loads(completed.stdout)["execute"])
