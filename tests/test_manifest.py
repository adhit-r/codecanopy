import json
import os
import tempfile
import unittest
from pathlib import Path

from runtime.manifest import INVALIDATION_RULE, MAX_MANIFEST_BYTES, ManifestError, ManifestStore


class ManifestStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "run.jsonl"
        self.store = ManifestStore(self.path)
        self.store.create_run("run-1", state="planned", branch="codex/demo")

    def tearDown(self):
        self.directory.cleanup()

    def test_appends_and_reloads_a_snapshot(self):
        self.store.record_node("run-1", "root", state="ready", objective="ship")
        self.store.set_node_state("run-1", "root", "active")

        snapshot = ManifestStore(self.path).snapshot("run-1")

        self.assertEqual("active", snapshot["nodes"]["root"]["state"])
        rows = [json.loads(line) for line in self.path.read_text().splitlines()]
        self.assertEqual([1, 2, 3], [row["seq"] for row in rows])

    def test_records_immutable_baseline_dependency_commits_and_checks(self):
        self.store.record_node("run-1", "build", state="ready")
        self.store.set_node_state("run-1", "build", "active")
        self.store.set_node_state("run-1", "build", "returned")
        self.store.set_node_state("run-1", "build", "accepted")
        self.store.record_node(
            "run-1",
            "interface",
            parent_id="build",
            dependencies=["build"],
            baseline={"commit": "base-abc", "dependency_commits": {"build": "dep-123"}},
        )
        self.store.record_check("run-1", "interface", "python3 -m unittest", "passed", evidence="tests/test_manifest.py")

        node = ManifestStore(self.path).snapshot("run-1")["nodes"]["interface"]
        self.assertEqual("base-abc", node["baseline"]["commit"])
        self.assertEqual({"build": "dep-123"}, node["baseline"]["dependency_commits"])
        self.assertEqual("passed", node["checks"][0]["result"])

    def test_recovery_never_claims_interrupted_active_nodes_completed(self):
        self.store.record_node("run-1", "retry", state="ready")
        self.store.set_node_state("run-1", "retry", "active")
        self.store.record_node("run-1", "needs-input", state="ready")
        self.store.set_node_state("run-1", "needs-input", "active")

        self.assertEqual(["retry", "needs-input"], self.store.recover_interrupted("run-1", blocked=["needs-input"]))

        nodes = ManifestStore(self.path).snapshot("run-1")["nodes"]
        self.assertEqual("ready", nodes["retry"]["state"])
        self.assertEqual("blocked", nodes["needs-input"]["state"])
        self.assertNotIn("accepted", {nodes["retry"]["state"], nodes["needs-input"]["state"]})

    def test_invalidation_stays_with_downstream_descendants(self):
        self.store.record_node("run-1", "source", state="ready")
        self.store.set_node_state("run-1", "source", "active")
        self.store.set_node_state("run-1", "source", "returned")
        self.store.set_node_state("run-1", "source", "accepted")
        self.store.record_node("run-1", "affected", parent_id="source", dependencies=["source"], state="ready")
        self.store.record_node("run-1", "nested", parent_id="affected", state="ready")
        self.store.record_node("run-1", "unrelated", state="ready")

        self.assertEqual(["affected", "nested"], self.store.invalidate_descendants("run-1", "source", "dependency changed"))

        nodes = ManifestStore(self.path).snapshot("run-1")["nodes"]
        self.assertEqual("invalidated", nodes["affected"]["state"])
        self.assertEqual("invalidated", nodes["nested"]["state"])
        self.assertEqual("ready", nodes["unrelated"]["state"])
        self.assertEqual(INVALIDATION_RULE, nodes["nested"]["invalidations"][0]["rule"])

    def test_status_reports_critical_frontier_and_node_counts(self):
        self.store.record_node("run-1", "contract", state="ready")
        self.store.set_node_state("run-1", "contract", "active")
        self.store.set_node_state("run-1", "contract", "returned")
        self.store.set_node_state("run-1", "contract", "accepted")
        self.store.record_node("run-1", "backend", dependencies=["contract"], state="ready")
        self.store.record_node("run-1", "ui", dependencies=["backend"], state="ready")

        status = self.store.status("run-1")

        self.assertEqual("planned", status["state"])
        self.assertEqual(["backend"], status["critical_frontier"])
        self.assertEqual({"accepted": 1, "ready": 2}, status["node_counts"])

    def test_inspect_node_returns_recorded_evidence(self):
        self.store.record_node("run-1", "contract", state="ready", objective="define")
        self.store.record_check("run-1", "contract", "unit", "passed")

        node = self.store.inspect_node("run-1", "contract")

        self.assertEqual("define", node["details"]["objective"])
        self.assertEqual("passed", node["checks"][0]["result"])

    def test_illegal_or_unknown_manifest_events_fail_closed(self):
        rows = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]
        rows.append({"seq": 2, "kind": "node-state", "run_id": "run-1", "node_id": "missing", "state": "accepted"})
        self.path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        with self.assertRaises(ManifestError):
            ManifestStore(self.path).snapshot("run-1")

    def test_manifest_rejects_symlink_without_touching_target(self):
        target = Path(self.directory.name) / "target"
        target.write_text("untouched", encoding="utf-8")
        link = Path(self.directory.name) / "linked.jsonl"
        link.symlink_to(target)
        with self.assertRaises(ManifestError):
            ManifestStore(link).create_run("unsafe")
        self.assertEqual("untouched", target.read_text(encoding="utf-8"))

    def test_oversized_manifest_is_rejected_before_parsing(self):
        oversized = Path(self.directory.name) / "oversized.jsonl"
        descriptor = os.open(oversized, os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            os.ftruncate(descriptor, MAX_MANIFEST_BYTES + 1)
        finally:
            os.close(descriptor)
        with self.assertRaisesRegex(ManifestError, "size limit"):
            ManifestStore(oversized).snapshot("run-1")


if __name__ == "__main__":
    unittest.main()
