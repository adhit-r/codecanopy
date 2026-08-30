import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
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
    def test_case_hash_binds_manifest_dag_and_oracle(self):
        case = paired_codex.load_case_definition(paired_codex.CASE_ROOT / "small")
        original = paired_codex.canonical_case_definition_hash(case)
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "small"
            shutil.copytree(paired_codex.CASE_ROOT / "small", copied)
            oracle = copied / "oracle.json"
            oracle.write_text(oracle.read_text().replace('"medium"', '"high"'), encoding="utf-8")
            changed = paired_codex.canonical_case_definition_hash(
                paired_codex.load_case_definition(copied)
            )
        self.assertNotEqual(original, changed)

    def test_provider_repository_contains_only_manifest_files(self):
        case = paired_codex.load_case_definition(paired_codex.CASE_ROOT / "medium")
        with tempfile.TemporaryDirectory() as directory:
            repo, baseline, tree_hash = paired_codex.copy_case_repo(case, Path(directory))
            tracked = subprocess.run(
                ["git", "-C", str(repo), "ls-files"], check=True, capture_output=True, text=True
            ).stdout.splitlines()
            visible = sorted(
                path.relative_to(repo).as_posix()
                for path in repo.rglob("*")
                if path.is_file() and ".git" not in path.parts
            )
        self.assertEqual(list(case.copy_manifest), sorted(tracked))
        self.assertEqual(list(case.copy_manifest), visible)
        self.assertNotIn("oracle.json", visible)
        self.assertNotIn("dag.json", visible)
        self.assertRegex(baseline, r"^[0-9a-f]{40,64}$")
        self.assertRegex(tree_hash, r"^[0-9a-f]{40,64}$")

    def test_case_loader_rejects_invalid_paths_and_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "case"
            (root / "subject").mkdir(parents=True)
            (root / "task.txt").write_text("review", encoding="utf-8")
            (root / "subject" / "one.py").write_text("pass\n", encoding="utf-8")
            (root / "copy-manifest.json").write_text(
                '{"paths":["task.txt","subject/one.py"]}', encoding="utf-8"
            )
            (root / "dag.json").write_text(
                '{"nodes":[{"complexity_score":0.1,"id":"one","role":"worker",'
                '"scope":["subject/one.py"],"size_score":0.1}]}', encoding="utf-8"
            )
            (root / "oracle.json").write_text(
                '{"findings":[{"category":"correctness","description":"defect",'
                '"end_line":1,"file":"subject/one.py","severity":"medium","start_line":1}]}',
                encoding="utf-8",
            )
            paired_codex.load_case_definition(root)
            for path in ("/task.txt", "../task.txt", "subject\\one.py"):
                (root / "copy-manifest.json").write_text(
                    json.dumps({"paths": [path]}), encoding="utf-8"
                )
                with self.assertRaises(ValueError):
                    paired_codex.load_case_definition(root)
            (root / "copy-manifest.json").write_text(
                '{"paths":["task.txt","task.txt"]}', encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                paired_codex.load_case_definition(root)
            (root / "copy-manifest.json").write_text(
                '{"paths":["task.txt","outside.py"]}', encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                paired_codex.load_case_definition(root)
            (root / "copy-manifest.json").write_text(
                '{"paths":["task.txt","subject/missing.py"]}', encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                paired_codex.load_case_definition(root)

    def test_case_loader_rejects_invalid_oracle_and_dag_contracts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "case"
            shutil.copytree(paired_codex.CASE_ROOT / "small", root)
            (root / "oracle.json").write_text(
                '{"findings":[{"category":"correctness","description":"one",'
                '"end_line":2,"file":"subject/percentage.py","severity":"medium","start_line":2},'
                '{"category":"correctness","description":"two","end_line":2,'
                '"file":"subject/percentage.py","severity":"medium","start_line":2}]}',
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                paired_codex.load_case_definition(root)
            (root / "oracle.json").write_text(
                '{"findings":[{"category":"unknown","description":"one",'
                '"end_line":2,"file":"subject/percentage.py","severity":"unknown","start_line":2}]}',
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                paired_codex.load_case_definition(root)
            (root / "oracle.json").write_bytes(
                (paired_codex.CASE_ROOT / "small" / "oracle.json").read_bytes()
            )
            for forbidden_key in ("model", "provider"):
                (root / "dag.json").write_text(
                    json.dumps({"nodes": [{
                        "complexity_score": 0.1,
                        "id": "one",
                        forbidden_key: "codex",
                        "role": "worker",
                        "scope": ["subject/percentage.py"],
                        "size_score": 0.1,
                    }]}),
                    encoding="utf-8",
                )
                with self.assertRaises(ValueError):
                    paired_codex.load_case_definition(root)
            (root / "dag.json").write_text(
                '{"nodes":[{"complexity_score":0.1,"id":"one","role":"worker",'
                '"scope":["subject/percentage.py"],"size_score":0.1},'
                '{"complexity_score":0.2,"id":"two","role":"worker",'
                '"scope":["subject/percentage.py"],"size_score":0.2}]}',
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                paired_codex.load_case_definition(root)

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

    def test_unexpected_top_level_field_is_incomplete(self):
        changed = OBSERVED_JSONL.replace(
            '"item": {"id": "redacted"',
            '"new_schema_field": true, "item": {"id": "redacted"',
        )
        self.assertIn("unexpected_telemetry_shape", paired_codex.parse_jsonl(changed).incomplete_reasons)

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
