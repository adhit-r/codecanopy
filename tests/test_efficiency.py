from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from runtime.efficiency import (
    SplitPolicy,
    inline_scope,
    load_split_policy,
    merge_findings,
    scope_work_tokens,
    scopes_disjoint,
    split_decision,
)
from runtime.tree import TreeNode


ASSET = Path("plugins/code-canopy/skills/code-canopy/assets/codecanopy.toml")


class SplitDecisionTests(unittest.TestCase):
    def test_bundled_policy_loads(self) -> None:
        self.assertEqual(SplitPolicy(), load_split_policy(ASSET))

    def test_small_leaves_collapse_to_one_agent(self) -> None:
        decision = split_decision({"a": 50, "b": 40}, SplitPolicy())
        self.assertFalse(decision.split)
        self.assertEqual(90, decision.total_work_tokens)

    def test_single_leaf_never_splits(self) -> None:
        self.assertFalse(split_decision({"a": 10**9}, SplitPolicy()).split)

    def test_large_leaves_split(self) -> None:
        policy = SplitPolicy(agent_overhead_tokens=2_000, min_work_to_overhead_ratio=3)
        self.assertTrue(split_decision({"a": 6_000, "b": 9_000}, policy).split)
        self.assertFalse(split_decision({"a": 5_999, "b": 9_000}, policy).split)

    def test_context_ceiling_forces_split(self) -> None:
        policy = SplitPolicy(single_agent_context_tokens=100)
        decision = split_decision({"a": 60, "b": 60}, policy)
        self.assertTrue(decision.split)
        self.assertIn("ceiling", decision.reason)

    def test_invalid_policy_and_empty_plan_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            SplitPolicy(agent_overhead_tokens=0)
        with self.assertRaises(ValueError):
            split_decision({}, SplitPolicy())


class LeanLeafTests(unittest.TestCase):
    def test_inline_scope_numbers_lines_inside_untrusted_delimiters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.py").write_bytes(b"x = 1\ny = 2\n")
            text = inline_scope(root, ["a.py"])
            self.assertEqual(3, scope_work_tokens(root, ["a.py"]))
        self.assertIn("--- BEGIN UNTRUSTED FILE a.py ---\n1: x = 1\n2: y = 2", text)
        self.assertIn("--- END UNTRUSTED FILE a.py ---", text)

    def test_inline_scope_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "big.py").write_text("x" * 30_000, encoding="utf-8")
            with self.assertRaises(ValueError):
                inline_scope(root, ["big.py"])

    def test_tree_node_accepts_only_boolean_lean(self) -> None:
        base = {"id": "a", "prompt": "p", "model_tier": "worker"}
        self.assertTrue(TreeNode.from_mapping({**base, "lean": True}).lean)
        self.assertFalse(TreeNode.from_mapping(base).lean)
        with self.assertRaises(ValueError):
            TreeNode.from_mapping({**base, "lean": "yes"})


class MergeTests(unittest.TestCase):
    def test_merge_is_deterministic_and_deduplicates(self) -> None:
        finding = {"file": "a.py", "start_line": 1, "end_line": 2, "category": "security", "severity": "high", "summary": "x"}
        later = {**finding, "file": "b.py"}
        artifacts = {
            "b": json.dumps({"findings": [later]}),
            "a": json.dumps({"findings": [finding, dict(finding, summary="duplicate")]}),
        }
        merged = json.loads(merge_findings(artifacts))["findings"]
        self.assertEqual([finding, later], merged)
        self.assertEqual(merge_findings(artifacts), merge_findings(dict(reversed(list(artifacts.items())))))

    def test_scopes_disjoint(self) -> None:
        self.assertTrue(scopes_disjoint({"a": ["x"], "b": ["y"]}))
        self.assertFalse(scopes_disjoint({"a": ["x"], "b": ["x", "y"]}))


if __name__ == "__main__":
    unittest.main()
