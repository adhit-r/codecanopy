import json
import tempfile
import unittest
from pathlib import Path

from runtime.manifest import ManifestError, ManifestStore
from runtime.providers import ProviderResult
from runtime.tree import TreeNode, run_tree


class MixedTreeTests(unittest.TestCase):
    def test_codex_and_claude_nodes_run_in_dependency_order_and_are_recorded(self):
        calls = []

        def fake_execute(request):
            calls.append((request.preferred_provider, request.prompt))
            return ProviderResult("completed", request.preferred_provider, request.preferred_provider, False, 0, "ok", None, {})

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = [
                TreeNode("contract", "define contract", "codex"),
                TreeNode("backend", "implement backend", "codex", ("contract",)),
                TreeNode("ui", "implement UI", "claude", ("contract",)),
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
            self.assertEqual("run-created", first_event["kind"])
            self.assertTrue((root / "receipts" / "ui.jsonl").exists())

    def test_failed_parent_leaves_dependent_ready_without_running_it(self):
        calls = []

        def fake_execute(request):
            calls.append(request.preferred_provider)
            return ProviderResult("failed", request.preferred_provider, request.preferred_provider, False, 1, "", "failed", {})

        with tempfile.TemporaryDirectory() as directory:
            result = run_tree(
                [TreeNode("contract", "fail", "codex"), TreeNode("ui", "should not run", "claude", ("contract",))],
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
            result = run_tree(
                [TreeNode("contract", "define", "codex")],
                manifest_path=Path(directory) / "run.jsonl",
                run_id="returned",
                execute=fake_execute,
            )
        self.assertEqual("returned", result["nodes"]["contract"]["status"])


if __name__ == "__main__":
    unittest.main()
