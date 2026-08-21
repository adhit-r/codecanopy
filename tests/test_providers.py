from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from runtime import providers


class ProviderTests(unittest.TestCase):
    def test_capability_uses_which_and_optional_safe_version_probe(self) -> None:
        runner = Mock(return_value=subprocess.CompletedProcess(["codex"], 0, "codex 1.2\n", ""))
        capability = providers.provider_capability("codex", probe_version=True, which=lambda _: "/bin/codex", runner=runner)
        self.assertEqual((capability.available, capability.version), (True, "codex 1.2"))
        self.assertEqual(runner.call_args.kwargs["timeout"], 5)

    def test_claude_fallback_to_codex_is_explicit(self) -> None:
        runner = Mock(return_value=subprocess.CompletedProcess([], 0, "done", ""))
        result = providers.execute_provider(
            providers.ProviderRequest("do work", preferred_provider="claude"),
            which=lambda name: "/bin/codex" if name == "codex" else None,
            runner=runner,
        )
        self.assertEqual((result.status, result.provider, result.fallback_used), ("completed", "codex", True))
        self.assertEqual(result.receipt_data["fallback_reason"], "preferred provider executable unavailable")
        self.assertEqual(runner.call_args.args[0], ("/bin/codex", "exec", "--json", "do work"))

    def test_timeout_returns_a_normalized_result(self) -> None:
        result = providers.execute_provider(
            providers.ProviderRequest("do work", timeout_seconds=2),
            which=lambda _: "/bin/codex",
            runner=Mock(side_effect=subprocess.TimeoutExpired("codex", 2)),
        )
        self.assertEqual((result.status, result.provider), ("timed_out", "codex"))

    def test_provider_environment_does_not_share_known_credentials(self) -> None:
        runner = Mock(return_value=subprocess.CompletedProcess([], 0, "done", ""))
        with patch.dict(os.environ, {"OPENAI_API_KEY": "openai", "ANTHROPIC_API_KEY": "anthropic", "CODEX_API_KEY": "codex"}):
            providers.execute_provider(
                providers.ProviderRequest("do work", preferred_provider="claude"),
                which=lambda name: "/bin/claude" if name == "claude" else None,
                runner=runner,
            )
        environment = runner.call_args.kwargs["env"]
        self.assertNotIn("OPENAI_API_KEY", environment)
        self.assertNotIn("CODEX_API_KEY", environment)
        self.assertEqual("anthropic", environment["ANTHROPIC_API_KEY"])

    def test_receipt_hashes_secrets_without_persisting_them(self) -> None:
        request = providers.ProviderRequest("token=secret")
        result = providers.ProviderResult("completed", "codex", "codex", False, 0, "answer=secret", None, {"leaked": "secret"})
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "receipt.jsonl"
            providers.append_proof_receipt(receipt, request, result)
            text = receipt.read_text(encoding="utf-8")
        self.assertNotIn("secret", text)
        self.assertEqual(json.loads(text)["prompt_hash"], providers._hash("token=secret"))

    def test_worktree_rejects_path_traversal_before_running_git(self) -> None:
        runner = Mock()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                providers.prepare_isolated_worktree(".", directory, "../escape", runner=runner)
        runner.assert_not_called()

    def test_worktree_add_is_detached_below_root(self) -> None:
        runner = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
        with tempfile.TemporaryDirectory() as directory:
            target = providers.prepare_isolated_worktree(".", directory, "worker-a", runner=runner)
            self.assertEqual(target.parent, Path(directory).resolve())
        self.assertIn("--detach", runner.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
