import json
import tempfile
import unittest
from pathlib import Path

from runtime.manifest import INVALIDATION_RULE, ManifestStore


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
        self.store.record_node("run-1", "build", state="accepted")
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
        self.store.record_node("run-1", "retry", state="active")
        self.store.record_node("run-1", "needs-input", state="active")

        self.assertEqual(["retry", "needs-input"], self.store.recover_interrupted("run-1", blocked=["needs-input"]))

        nodes = ManifestStore(self.path).snapshot("run-1")["nodes"]
        self.assertEqual("ready", nodes["retry"]["state"])
        self.assertEqual("blocked", nodes["needs-input"]["state"])
        self.assertNotIn("accepted", {nodes["retry"]["state"], nodes["needs-input"]["state"]})

    def test_invalidation_stays_with_downstream_descendants(self):
        self.store.record_node("run-1", "source", state="accepted")
        self.store.record_node("run-1", "affected", parent_id="source", dependencies=["source"], state="ready")
        self.store.record_node("run-1", "nested", parent_id="affected", state="ready")
        self.store.record_node("run-1", "unrelated", state="ready")

        self.assertEqual(["affected", "nested"], self.store.invalidate_descendants("run-1", "source", "dependency changed"))

        nodes = ManifestStore(self.path).snapshot("run-1")["nodes"]
        self.assertEqual("invalidated", nodes["affected"]["state"])
        self.assertEqual("invalidated", nodes["nested"]["state"])
        self.assertEqual("ready", nodes["unrelated"]["state"])
        self.assertEqual(INVALIDATION_RULE, nodes["nested"]["invalidations"][0]["rule"])


if __name__ == "__main__":
    unittest.main()
