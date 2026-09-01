from pathlib import Path
import tempfile
import unittest

from benchmarks.model_routing import NodeSignal, load_config, route_node


ASSET = Path("plugins/code-canopy/skills/code-canopy/assets/codecanopy.toml")


class ModelRoutingTests(unittest.TestCase):
    def test_checked_in_asset_preserves_selected_effort(self):
        config = load_config(ASSET)
        expected_efforts = {"lead": "high", "expert": "high", "worker": "medium", "reviewer": "high"}
        self.assertEqual(expected_efforts, {
            tier: settings.reasoning_effort for tier, settings in config.models.items()
        })
        self.assertEqual({"auto"}, {settings.model for settings in config.models.values()})

    def test_each_override_retains_its_configured_effort(self):
        config = load_config(ASSET)
        cases = (
            (NodeSignal("small", "worker", 0.1, 0.1), "worker", "medium"),
            (NodeSignal("security", "security", 0.1, 0.1), "lead", "high"),
            (NodeSignal("review", "reviewer", 0.1, 0.1), "reviewer", "high"),
            (NodeSignal("uncertain", "worker", None, None), "expert", "high"),
        )
        for node, tier, effort in cases:
            with self.subTest(node=node.name):
                decision = route_node(node, config)
                self.assertEqual((tier, "auto", effort), (
                    decision.tier, decision.model, decision.reasoning_effort
                ))

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

    def test_invalid_model_discovery_values_are_rejected(self):
        text = ASSET.read_text(encoding="utf-8")
        invalid_configs = (
            text.replace('mode = "automatic"', 'mode = "manual"'),
            text.replace('release_channel = "ga"', 'release_channel = "preview"'),
            text.replace('refresh = "run_start"', 'refresh = "resume"'),
            text.replace('on_failure = "fail"', 'on_failure = "fallback"'),
        )
        for invalid in invalid_configs:
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "config.toml"
                path.write_text(invalid, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "model discovery"):
                    load_config(path)
