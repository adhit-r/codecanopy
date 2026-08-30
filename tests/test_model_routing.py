from pathlib import Path
import tempfile
import unittest

from benchmarks.model_routing import NodeSignal, load_config, route_node


ASSET = Path("plugins/code-canopy/skills/code-canopy/assets/codecanopy.toml")


class ModelRoutingTests(unittest.TestCase):
    def test_checked_in_asset_preserves_selected_effort(self):
        config = load_config(ASSET)
        decision = route_node(NodeSignal("small", "worker", 0.1, 0.1), config)
        self.assertEqual(("worker", "gpt-5.6-luna", "medium"), (
            decision.tier, decision.model, decision.reasoning_effort
        ))

    def test_each_override_retains_its_configured_effort(self):
        config = load_config(ASSET)
        cases = (
            (NodeSignal("security", "security", 0.1, 0.1), "lead", "high"),
            (NodeSignal("review", "reviewer", 0.1, 0.1), "reviewer", "high"),
            (NodeSignal("uncertain", "worker", None, None), "expert", "high"),
        )
        for node, tier, effort in cases:
            with self.subTest(node=node.name):
                decision = route_node(node, config)
                self.assertEqual((tier, effort), (decision.tier, decision.reasoning_effort))

    def test_invalid_or_missing_effort_is_rejected(self):
        text = ASSET.read_text(encoding="utf-8")
        invalid_configs = (
            text.replace('reasoning_effort = "medium"', 'reasoning_effort = "fast"'),
            text.replace('reasoning_effort = "medium"\n', ''),
        )
        for invalid in invalid_configs:
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "config.toml"
                path.write_text(invalid, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "reasoning effort"):
                    load_config(path)
