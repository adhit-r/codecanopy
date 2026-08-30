import io
import json
import os
import stat
from dataclasses import FrozenInstanceError, asdict, replace
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


def fake_run_contract():
    return paired_codex.RunContract(
        benchmark_version="codex-readonly-v1",
        scorer_version="finding-overlap-v1",
        cli_version="codex-cli 0.147.0",
        adapter_fingerprint="a" * 64,
        routing_config_hash="b" * 64,
        timeout_seconds=120,
        sandbox="read-only",
        acceptance_contract_hash="c" * 64,
    )


def fake_case_snapshots():
    return tuple(
        paired_codex.CaseSnapshot(
            case_id,
            baseline=str(index) * 40,
            subject_tree_hash=str(index + 3) * 40,
            case_definition_hash=str(index + 6) * 64,
        )
        for index, case_id in enumerate(("small", "medium", "complex"), 1)
    )


class PairedCodexTests(unittest.TestCase):
    def test_seeded_schedule_has_nine_pairs_and_eighteen_unique_positions(self):
        contract = fake_run_contract()
        cases = fake_case_snapshots()
        first = paired_codex.build_schedule(41, contract, cases)
        second = paired_codex.build_schedule(41, contract, cases)
        self.assertEqual(first, second)
        self.assertEqual(18, len(first.entries))
        self.assertEqual(list(range(18)), [entry.position for entry in first.entries])
        pairs = {(entry.case_id, entry.repetition) for entry in first.entries}
        self.assertEqual(9, len(pairs))
        for pair in pairs:
            self.assertEqual(
                {"sequential", "canopy"},
                {
                    entry.arm
                    for entry in first.entries
                    if (entry.case_id, entry.repetition) == pair
                },
            )
        with self.assertRaises(FrozenInstanceError):
            first.entries[0].arm = "changed"

    def test_schedule_requires_canonical_contract_and_exact_case_snapshots(self):
        contract = fake_run_contract()
        cases = fake_case_snapshots()
        canonical = paired_codex.build_schedule(41, contract, cases)
        reordered = paired_codex.build_schedule(41, contract, tuple(reversed(cases)))
        self.assertEqual(canonical, reordered)
        invalid_inputs = (
            (contract, cases[:-1]),
            (contract, (cases[0], cases[0], cases[2])),
            (contract, (replace(cases[0], case_id=["small"]), *cases[1:])),
            (contract, (replace(cases[0], baseline="not-a-hash"), *cases[1:])),
            (replace(contract, routing_config_hash="not-a-hash"), cases),
        )
        for invalid_contract, invalid_cases in invalid_inputs:
            with self.subTest(contract=invalid_contract, cases=invalid_cases):
                with self.assertRaises(ValueError):
                    paired_codex.build_schedule(41, invalid_contract, invalid_cases)

    def test_result_record_is_canonical_private_and_durable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private" / "results.jsonl"
            paired_codex.append_result_record(path, {"z": 1, "a": "value"})
            self.assertEqual(b'{"a":"value","z":1}\n', path.read_bytes())
            self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))

    def test_result_limits_leave_existing_ledger_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.jsonl"
            paired_codex.append_result_record(path, {"kind": "schedule", "entries": []})
            original = path.read_bytes()
            with patch.object(paired_codex, "MAX_RESULT_EVENTS", 1):
                with self.assertRaisesRegex(ValueError, "event limit"):
                    paired_codex.append_result_record(path, {"kind": "arm-result"})
            self.assertEqual(original, path.read_bytes())

    def test_result_rejects_preexisting_oversize_before_scanning(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.jsonl"
            path.write_bytes(b"x" * (paired_codex.MAX_RESULT_BYTES + 1))
            original = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "size limit"):
                paired_codex.append_result_record(path, {"kind": "arm-result"})
            self.assertEqual(original, path.read_bytes())

    def test_result_enforces_exact_event_size_boundary(self):
        overhead = len(b'{"payload":""}\n')
        exact = {"payload": "x" * (paired_codex.MAX_RESULT_EVENT_BYTES - overhead)}
        oversized = {"payload": exact["payload"] + "x"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.jsonl"
            paired_codex.append_result_record(path, exact)
            original = path.read_bytes()
            self.assertEqual(paired_codex.MAX_RESULT_EVENT_BYTES, len(original))
            with self.assertRaisesRegex(ValueError, "event size limit"):
                paired_codex.append_result_record(path, oversized)
            self.assertEqual(original, path.read_bytes())

    def test_result_rejects_the_event_after_one_thousand_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.jsonl"
            path.write_bytes(b'{}\n' * paired_codex.MAX_RESULT_EVENTS)
            original = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "event limit"):
                paired_codex.append_result_record(path, {"kind": "arm-result"})
            self.assertEqual(original, path.read_bytes())

    def test_result_rejects_symlinks_and_hard_links_without_changing_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for link_kind in ("symlink", "hardlink"):
                with self.subTest(link_kind=link_kind):
                    target = root / f"{link_kind}-target"
                    target.write_bytes(b"untouched")
                    result = root / f"{link_kind}-results.jsonl"
                    if link_kind == "symlink":
                        result.symlink_to(target)
                    else:
                        os.link(target, result)
                    with self.assertRaises(ValueError):
                        paired_codex.append_result_record(result, {"kind": "arm-result"})
                    self.assertEqual(b"untouched", target.read_bytes())

    def test_result_loader_constructs_the_exact_first_schedule(self):
        schedule = paired_codex.build_schedule(41, fake_run_contract(), fake_case_snapshots())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.jsonl"
            paired_codex.append_result_record(path, {"kind": "schedule", **asdict(schedule)})
            loaded, records = paired_codex.load_results(path)
        self.assertEqual(schedule, loaded)
        self.assertEqual((), records)

    def test_result_loader_rejects_unknown_keys_and_later_schedule_rows(self):
        schedule = paired_codex.build_schedule(41, fake_run_contract(), fake_case_snapshots())
        record = {"kind": "schedule", **asdict(schedule)}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.jsonl"
            paired_codex.append_result_record(path, record)
            paired_codex.append_result_record(path, record)
            original = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "schedule"):
                paired_codex.load_results(path)
            self.assertEqual(original, path.read_bytes())

    def test_result_loader_rejects_boolean_schedule_positions(self):
        schedule = paired_codex.build_schedule(41, fake_run_contract(), fake_case_snapshots())
        record = {"kind": "schedule", **asdict(schedule)}
        record["entries"][0]["position"] = False
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.jsonl"
            paired_codex.append_result_record(path, record)
            original = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "schedule entry"):
                paired_codex.load_results(path)
            self.assertEqual(original, path.read_bytes())
            path.write_bytes(json.dumps({**record, "unknown": True}).encode() + b"\n")
            path.chmod(0o600)
            original = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "schedule"):
                paired_codex.load_results(path)
            self.assertEqual(original, path.read_bytes())

    def test_receipt_auditor_requires_one_matching_output_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "receipts" / "000-small-sequential" / "lead.jsonl"
            receipt.parent.mkdir(parents=True)
            receipt.write_text(json.dumps({"output_hash": "a" * 64}) + "\n", encoding="utf-8")
            receipt.chmod(0o600)
            reference = receipt.relative_to(root).as_posix()
            paired_codex.audit_proof_receipt(root, reference, "a" * 64)
            with self.assertRaisesRegex(ValueError, "output hash"):
                paired_codex.audit_proof_receipt(root, reference, "b" * 64)
            receipt.write_text(receipt.read_text() * 2, encoding="utf-8")
            original = receipt.read_bytes()
            with self.assertRaisesRegex(ValueError, "exactly one"):
                paired_codex.audit_proof_receipt(root, reference, "a" * 64)
            self.assertEqual(original, receipt.read_bytes())

    def test_receipt_auditor_rejects_unsafe_paths_links_and_oversize(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.jsonl"
            target.write_text(json.dumps({"output_hash": "a" * 64}) + "\n", encoding="utf-8")
            target.chmod(0o600)
            for reference in ("/absolute.jsonl", "../parent.jsonl", "receipts\\backslash.jsonl"):
                with self.subTest(reference=reference), self.assertRaises(ValueError):
                    paired_codex.audit_proof_receipt(root, reference, "a" * 64)
            for link_kind in ("symlink", "hardlink"):
                with self.subTest(link_kind=link_kind):
                    linked = root / f"{link_kind}.jsonl"
                    if link_kind == "symlink":
                        linked.symlink_to(target)
                    else:
                        os.link(target, linked)
                    original = target.read_bytes()
                    with self.assertRaises(ValueError):
                        paired_codex.audit_proof_receipt(root, linked.name, "a" * 64)
                    self.assertEqual(original, target.read_bytes())
            oversized = root / "oversized.jsonl"
            oversized.write_bytes(b"x" * (paired_codex.MAX_RECEIPT_EVENT_BYTES + 1))
            oversized.chmod(0o600)
            original = oversized.read_bytes()
            with self.assertRaisesRegex(ValueError, "size limit"):
                paired_codex.audit_proof_receipt(root, oversized.name, "a" * 64)
            self.assertEqual(original, oversized.read_bytes())

    def test_model_finding_parser_normalizes_manifest_paths(self):
        case = paired_codex.load_case_definition(paired_codex.CASE_ROOT / "small")
        parsed = paired_codex.parse_model_findings(json.dumps({"findings": [{
            "file": "subject/./percentage.py",
            "start_line": 2,
            "end_line": 2,
            "category": "correctness",
            "severity": "medium",
            "description": "division by zero",
        }]}), case)
        self.assertEqual((), parsed.incomplete_reasons)
        self.assertEqual((paired_codex.Finding(
            "subject/percentage.py", 2, 2, "correctness", "medium", "division by zero"
        ),), parsed.findings)

    def test_model_finding_parser_marks_malformed_or_oversized_output_incomplete(self):
        case = paired_codex.load_case_definition(paired_codex.CASE_ROOT / "small")
        for output in ("not JSON", " " * (paired_codex.MAX_MODEL_FINDINGS_BYTES + 1)):
            with self.subTest(output_size=len(output)):
                parsed = paired_codex.parse_model_findings(output, case)
                self.assertIsNone(parsed.findings)
                self.assertTrue(parsed.incomplete_reasons)

    def test_model_finding_parser_requires_the_oracle_contract(self):
        case = paired_codex.load_case_definition(paired_codex.CASE_ROOT / "small")
        valid = {
            "file": "subject/percentage.py",
            "start_line": 2,
            "end_line": 2,
            "category": "correctness",
            "severity": "medium",
            "description": "division by zero",
        }
        invalid_findings = (
            {**valid, "extra": "field"},
            {**valid, "file": "task.txt"},
            {**valid, "category": "unknown"},
            {**valid, "severity": "unknown"},
            {**valid, "start_line": 0},
            {**valid, "start_line": 2, "end_line": 1},
            {**valid, "end_line": 3},
            {**valid, "description": ""},
        )
        for finding in invalid_findings:
            with self.subTest(finding=finding):
                parsed = paired_codex.parse_model_findings(json.dumps({"findings": [finding]}), case)
                self.assertIsNone(parsed.findings)
                self.assertTrue(parsed.incomplete_reasons)

    def test_scorer_is_one_to_one_and_counts_duplicates_as_false_positives(self):
        expected = (
            paired_codex.Finding("subject/a.py", 10, 12, "security", "high", "expected"),
        )
        predicted = (
            paired_codex.Finding("subject/a.py", 10, 10, "security", "high", "first"),
            paired_codex.Finding("subject/a.py", 11, 11, "security", "high", "duplicate"),
        )
        score = paired_codex.score_findings(expected, predicted)
        self.assertEqual((1, 1, 0), (score.tp, score.fp, score.fn))
        self.assertEqual((0.5, 1.0, 2 / 3), (score.precision, score.recall, score.f1))
        self.assertFalse(score.accepted)

    def test_zero_predictions_scores_exactly_zero(self):
        expected = (
            paired_codex.Finding("subject/a.py", 1, 1, "correctness", "medium", "expected"),
        )
        score = paired_codex.score_findings(expected, ())
        self.assertEqual((0, 0, 1, 0.0, 0.0, 0.0, False), (
            score.tp, score.fp, score.fn, score.precision, score.recall, score.f1, score.accepted
        ))

    def test_unmatched_high_finding_blocks_acceptance(self):
        expected = (
            paired_codex.Finding("subject/a.py", 1, 1, "security", "high", "required"),
            paired_codex.Finding("subject/b.py", 1, 1, "correctness", "low", "minor"),
        )
        predicted = (
            paired_codex.Finding("subject/b.py", 1, 1, "correctness", "low", "found"),
        )
        self.assertFalse(paired_codex.score_findings(expected, predicted).accepted)

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

    def test_baseline_commit_ignores_parent_git_identity_environment(self):
        case = paired_codex.load_case_definition(paired_codex.CASE_ROOT / "small")
        first_identity = {
            "GIT_AUTHOR_NAME": "First Author",
            "GIT_AUTHOR_EMAIL": "first@example.test",
            "GIT_COMMITTER_NAME": "First Committer",
            "GIT_COMMITTER_EMAIL": "first-committer@example.test",
        }
        second_identity = {
            "GIT_AUTHOR_NAME": "Second Author",
            "GIT_AUTHOR_EMAIL": "second@example.test",
            "GIT_COMMITTER_NAME": "Second Committer",
            "GIT_COMMITTER_EMAIL": "second-committer@example.test",
        }
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, first_identity):
                _, first, _ = paired_codex.copy_case_repo(case, Path(directory) / "first")
            with patch.dict(os.environ, second_identity):
                _, second, _ = paired_codex.copy_case_repo(case, Path(directory) / "second")
        self.assertEqual(first, second)

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
