import json
import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from runtime.manifest import ManifestError, ManifestStore
from runtime.providers import ProviderResult
from runtime.tree import MAX_NODES, MAX_PLAN_BYTES, TreeNode, _load_plan, main, run_tree


class MixedTreeTests(unittest.TestCase):
    def test_codex_and_claude_nodes_run_in_dependency_order_and_are_recorded(self):
        calls = []

        def fake_execute(request):
            calls.append((request.preferred_provider, request.prompt))
            return ProviderResult("completed", request.preferred_provider, request.preferred_provider, False, 0, "ok", None, {})

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
            ).stdout.strip()
            plan = [
                TreeNode("contract", "define contract", "codex"),
                TreeNode("backend", "implement backend", "codex", ("contract",), dependency_commits={"contract": head}),
                TreeNode("ui", "implement UI", "claude", ("contract",), dependency_commits={"contract": head}),
            ]
            result = run_tree(
                plan,
                manifest_path=root / "run.jsonl",
                run_id="mixed",
                receipt_dir=root / "receipts",
                execute=fake_execute,
                accept=lambda _node, _result: True,
            )
            first_event = json.loads((root / "run.jsonl").read_text().splitlines()[0])

            self.assertEqual(["codex", "codex", "claude"], [provider for provider, _ in calls])
            self.assertEqual({"contract", "backend", "ui"}, set(result["nodes"]))
            self.assertEqual("accepted", result["nodes"]["ui"]["status"])
            self.assertEqual("completed", result["state"])
            self.assertEqual("run-created", first_event["kind"])
            self.assertTrue((root / "receipts" / "ui.jsonl").exists())

    def test_failed_parent_leaves_dependent_ready_without_running_it(self):
        calls = []

        def fake_execute(request):
            calls.append(request.preferred_provider)
            return ProviderResult("failed", request.preferred_provider, request.preferred_provider, False, 1, "", "failed", {})

        with tempfile.TemporaryDirectory() as directory:
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
            ).stdout.strip()
            result = run_tree(
                [
                    TreeNode("contract", "fail", "codex"),
                    TreeNode("ui", "should not run", "claude", ("contract",), dependency_commits={"contract": head}),
                ],
                manifest_path=Path(directory) / "run.jsonl",
                run_id="blocked",
                execute=fake_execute,
            )
        self.assertEqual(["codex"], calls)
        self.assertEqual("ready", result["nodes"]["ui"]["status"])

    def test_changed_saved_contract_is_rejected_before_redispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_tree(
                [TreeNode("contract", "define", "codex")],
                manifest_path=root / "run.jsonl",
                run_id="contract-change",
                execute=lambda request: ProviderResult(
                    "completed", request.preferred_provider, request.preferred_provider, False, 0, "ok", None, {}
                ),
                accept=lambda _node, _result: True,
            )
            with self.assertRaises(ManifestError):
                run_tree(
                    [TreeNode("contract", "changed", "codex")],
                    manifest_path=root / "run.jsonl",
                    run_id="contract-change",
                    execute=lambda _request: self.fail("changed contract must not execute"),
                )

    def test_trusted_settings_are_resolved_once_and_bound_to_each_node(self):
        calls = []
        resolutions = []
        policy_hash = "a" * 64

        def settings(node):
            resolutions.append(node.node_id)
            return {
                "one": ("gpt-5.6-luna", "medium"),
                "two": ("gpt-5.6-terra", "high"),
            }[node.node_id]

        def execute(request):
            calls.append((request.model, request.reasoning_effort))
            return ProviderResult("completed", "codex", "codex", False, 0, "ok", None, {})

        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "run.jsonl"
            run_tree(
                [TreeNode("one", "first"), TreeNode("two", "second")],
                manifest_path=manifest,
                run_id="settings",
                execution_settings=settings,
                execution_policy_hash=policy_hash,
                execute=execute,
            )
            snapshot = ManifestStore(manifest).snapshot("settings")

        self.assertEqual(["one", "two"], resolutions)
        self.assertEqual([("gpt-5.6-luna", "medium"), ("gpt-5.6-terra", "high")], calls)
        self.assertEqual(policy_hash, snapshot["nodes"]["one"]["details"]["execution_policy_hash"])

    def test_invalid_execution_settings_fail_before_manifest_or_execution(self):
        cases = (
            ("missing tuple", "codex", None, "exact 2-tuple"),
            ("short tuple", "codex", (None,), "exact 2-tuple"),
            ("long tuple", "codex", (None, None, None), "exact 2-tuple"),
            ("mutable pair", "codex", [None, None], "exact 2-tuple"),
            ("invalid model", "codex", ("../../escape", None), "model"),
            ("invalid effort", "codex", (None, "fast"), "reasoning_effort"),
            ("Claude model", "claude", ("claude-sonnet", None), "Claude"),
            ("Claude effort", "claude", (None, "high"), "Claude"),
        )
        for label, provider, settings, message in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                manifest = Path(directory) / "run.jsonl"
                resolutions = []
                executions = []

                def resolve(node):
                    resolutions.append(node.node_id)
                    return settings

                def execute(_request):
                    executions.append(True)
                    self.fail("invalid settings must not execute")

                with self.assertRaisesRegex(ValueError, message):
                    run_tree(
                        [TreeNode("one", "first", provider)],
                        manifest_path=manifest,
                        run_id="invalid-settings",
                        execution_settings=resolve,
                        execute=execute,
                    )

                self.assertEqual(["one"], resolutions)
                self.assertEqual([], executions)
                self.assertFalse(manifest.exists())

    def test_changed_policy_hash_rejects_recovery_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "run.jsonl"
            run_tree(
                [TreeNode("one", "first")],
                manifest_path=manifest,
                run_id="policy",
                execution_settings=lambda _node: ("gpt-5.6-luna", "medium"),
                execution_policy_hash="a" * 64,
                execute=lambda _request: ProviderResult("completed", "codex", "codex", False, 0, "ok", None, {}),
            )
            with self.assertRaises(ManifestError):
                run_tree(
                    [TreeNode("one", "first")],
                    manifest_path=manifest,
                    run_id="policy",
                    execution_settings=lambda _node: ("gpt-5.6-luna", "medium"),
                    execution_policy_hash="b" * 64,
                    execute=lambda _request: self.fail("changed policy must not execute"),
                )

    def test_changed_model_rejects_recovery_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "run.jsonl"
            run_tree(
                [TreeNode("one", "first")],
                manifest_path=manifest,
                run_id="model",
                execution_settings=lambda _node: ("gpt-5.6-luna", "medium"),
                execution_policy_hash="a" * 64,
                execute=lambda _request: ProviderResult("completed", "codex", "codex", False, 0, "ok", None, {}),
            )
            with self.assertRaises(ManifestError):
                run_tree(
                    [TreeNode("one", "first")],
                    manifest_path=manifest,
                    run_id="model",
                    execution_settings=lambda _node: ("gpt-5.6-terra", "medium"),
                    execution_policy_hash="a" * 64,
                    execute=lambda _request: self.fail("changed model must not execute"),
                )

    def test_changed_reasoning_effort_rejects_recovery_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "run.jsonl"
            run_tree(
                [TreeNode("one", "first")],
                manifest_path=manifest,
                run_id="effort",
                execution_settings=lambda _node: ("gpt-5.6-luna", "medium"),
                execution_policy_hash="a" * 64,
                execute=lambda _request: ProviderResult("completed", "codex", "codex", False, 0, "ok", None, {}),
            )
            with self.assertRaises(ManifestError):
                run_tree(
                    [TreeNode("one", "first")],
                    manifest_path=manifest,
                    run_id="effort",
                    execution_settings=lambda _node: ("gpt-5.6-luna", "high"),
                    execution_policy_hash="a" * 64,
                    execute=lambda _request: self.fail("changed reasoning effort must not execute"),
                )

    def test_invalid_execution_policy_hash_does_not_create_manifest(self):
        for policy_hash in ("A" * 64, "a" * 63, "g" * 64):
            with self.subTest(policy_hash=policy_hash), tempfile.TemporaryDirectory() as directory:
                manifest = Path(directory) / "run.jsonl"
                with self.assertRaisesRegex(ValueError, "lowercase SHA-256 digest"):
                    run_tree(
                        [TreeNode("one", "first")],
                        manifest_path=manifest,
                        run_id="invalid-policy",
                        execution_policy_hash=policy_hash,
                    )
                self.assertFalse(manifest.exists())

    def test_contract_validation_failure_does_not_mark_the_run_active(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "run.jsonl"
            with self.assertRaisesRegex(ManifestError, "could not resolve immutable baseline"):
                run_tree(
                    [TreeNode("contract", "define", baseline="0" * 40)],
                    manifest_path=manifest,
                    run_id="invalid-contract",
                    execute=lambda _request: self.fail("invalid contract must not execute"),
                )

            self.assertEqual("planned", ManifestStore(manifest).snapshot("invalid-contract")["state"])

    def test_default_baseline_is_materialized_as_a_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_tree(
                [TreeNode("contract", "define", "codex")],
                manifest_path=root / "run.jsonl",
                run_id="baseline",
                execute=lambda request: ProviderResult(
                    "completed", request.preferred_provider, request.preferred_provider, False, 0, "ok", None, {}
                ),
            )
            baseline = ManifestStore(root / "run.jsonl").snapshot("baseline")["nodes"]["contract"]["baseline"]["commit"]
            self.assertRegex(baseline, r"^[0-9a-f]{40,64}$")

    def test_successful_provider_result_stays_returned_without_acceptance(self):
        def fake_execute(request):
            return ProviderResult("completed", request.preferred_provider, request.preferred_provider, False, 0, "ok", None, {})

        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "run.jsonl"
            result = run_tree(
                [TreeNode("contract", "define", "codex")],
                manifest_path=manifest,
                run_id="returned",
                execute=fake_execute,
            )
            node_states = [
                row["state"]
                for row in map(json.loads, manifest.read_text(encoding="utf-8").splitlines())
                if row["kind"] == "node-state"
            ]
        self.assertEqual("returned", result["nodes"]["contract"]["status"])
        self.assertEqual("planned", result["state"])
        self.assertEqual(["active", "returned"], node_states)

    def test_cli_status_and_inspect_read_manifest_without_running_provider(self):
        def fake_execute(request):
            return ProviderResult("completed", request.preferred_provider, request.preferred_provider, False, 0, "ok", None, {})

        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "run.jsonl"
            run_tree(
                [TreeNode("contract", "define", "codex")],
                manifest_path=manifest,
                run_id="cli",
                execute=fake_execute,
                accept=lambda _node, _result: True,
            )
            status_output = io.StringIO()
            with redirect_stdout(status_output):
                self.assertEqual(0, main(["--status", "--manifest", str(manifest), "--run-id", "cli"]))
            inspect_output = io.StringIO()
            with redirect_stdout(inspect_output):
                self.assertEqual(0, main(["--inspect", "contract", "--manifest", str(manifest), "--run-id", "cli"]))

        self.assertEqual("completed", json.loads(status_output.getvalue())["state"])
        self.assertEqual("contract", json.loads(inspect_output.getvalue())["node_id"])

    def test_raw_prompt_is_not_persisted_in_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "run.jsonl"
            run_tree(
                [TreeNode("contract", "token=highly-sensitive")],
                manifest_path=manifest,
                run_id="private-prompt",
                execute=lambda request: ProviderResult(
                    "completed", request.preferred_provider, request.preferred_provider, False, 0, "ok", None, {}
                ),
            )
            text = manifest.read_text(encoding="utf-8")
        self.assertNotIn("highly-sensitive", text)
        self.assertIn("prompt_hash", text)

    def test_accepted_manifest_state_cannot_suppress_a_new_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "run.jsonl"
            run_tree(
                [TreeNode("contract", "define")],
                manifest_path=manifest,
                run_id="resume",
                execute=lambda request: ProviderResult(
                    "completed", request.preferred_provider, request.preferred_provider, False, 0, "ok", None, {}
                ),
                accept=lambda _node, _result: True,
            )
            with self.assertRaisesRegex(ManifestError, "cannot be resumed"):
                run_tree(
                    [TreeNode("contract", "define")],
                    manifest_path=manifest,
                    run_id="resume",
                    execute=lambda _request: self.fail("accepted node must not be silently trusted"),
                )

    def test_plan_cannot_select_repository_or_output_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / "plan.json"
            plan.write_text(
                json.dumps({"run_id": "unsafe", "nodes": [], "repo": "/private"}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "untrusted plan options"):
                _load_plan(plan)

    def test_plan_rejects_type_coercion(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / "plan.json"
            for node in ({"id": 1, "prompt": "work"}, {"id": "n", "prompt": 1}, {"id": "n", "prompt": "work", "depends_on": "root"}):
                plan.write_text(json.dumps({"run_id": "typed", "nodes": [node]}), encoding="utf-8")
                with self.assertRaises(ValueError):
                    _load_plan(plan)

    def test_dependency_commits_must_exactly_cover_dependencies(self):
        with self.assertRaisesRegex(ValueError, "exactly cover"):
            TreeNode("ui", "implement", depends_on=("contract",))
        with self.assertRaisesRegex(ValueError, "exactly cover"):
            TreeNode(
                "ui",
                "implement",
                depends_on=("contract", "design"),
                dependency_commits={"contract": "0" * 40},
            )

    def test_plan_read_is_byte_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / "plan.json"
            with plan.open("wb") as handle:
                handle.truncate(MAX_PLAN_BYTES + 1)
            with self.assertRaisesRegex(ValueError, "plan exceeds"):
                _load_plan(plan)

    def test_plan_rejects_symlinks_and_special_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.json"
            target.write_text(json.dumps({"run_id": "substitute", "nodes": []}), encoding="utf-8")
            link = root / "link.json"
            link.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "unsafe input file"):
                _load_plan(link)

            fifo = root / "plan.fifo"
            os.mkfifo(fifo)
            with self.assertRaisesRegex(ValueError, "not a regular file"):
                _load_plan(fifo)

    def test_tree_limits_node_count_depth_and_timeout(self):
        with self.assertRaises(ValueError):
            TreeNode("bad", "prompt", timeout_seconds=float("nan"))
        with self.assertRaisesRegex(ValueError, "1-9 nodes"):
            run_tree(
                [TreeNode(f"n{index}", "work") for index in range(MAX_NODES + 1)],
                manifest_path="unused.jsonl",
                run_id="too-many",
            )
        nodes = [TreeNode("n0", "work")]
        for index in range(1, 5):
            dependency = f"n{index - 1}"
            nodes.append(
                TreeNode(
                    f"n{index}",
                    "work",
                    depends_on=(dependency,),
                    dependency_commits={dependency: "0" * 40},
                )
            )
        with self.assertRaisesRegex(ValueError, "maximum dependency depth"):
            run_tree(nodes, manifest_path="unused.jsonl", run_id="too-deep")


if __name__ == "__main__":
    unittest.main()
