from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from runtime import providers


class ProviderTests(unittest.TestCase):
    def test_capability_uses_which_and_optional_safe_version_probe(self) -> None:
        runner = Mock(return_value=subprocess.CompletedProcess(["codex"], 0, "codex 1.2\n", ""))
        with patch.dict(os.environ, {"OPENAI_API_KEY": "must-not-reach-version-probe"}):
            capability = providers.provider_capability("codex", probe_version=True, which=lambda _: "/bin/codex", runner=runner)
        self.assertEqual((capability.available, capability.version), (True, "codex 1.2"))
        self.assertEqual(runner.call_args.kwargs["timeout"], 5)
        self.assertNotIn("OPENAI_API_KEY", runner.call_args.kwargs["env"])

    def test_claude_fallback_fails_closed_by_default(self) -> None:
        runner = Mock()
        result = providers.execute_provider(
            providers.ProviderRequest("do work", preferred_provider="claude"),
            which=lambda name: "/bin/codex" if name == "codex" else None,
            runner=runner,
        )
        self.assertEqual((result.status, result.provider, result.fallback_used), ("unavailable", None, False))
        runner.assert_not_called()

    def test_claude_fallback_to_codex_requires_explicit_opt_in(self) -> None:
        runner = Mock(return_value=subprocess.CompletedProcess([], 0, "done", ""))
        result = providers.execute_provider(
            providers.ProviderRequest("do work", preferred_provider="claude", allow_fallback=True),
            which=lambda name: "/bin/codex" if name == "codex" else None,
            runner=runner,
        )
        self.assertEqual((result.status, result.provider, result.fallback_used), ("completed", "codex", True))
        self.assertEqual(result.receipt_data["fallback_reason"], "preferred provider executable unavailable")
        command = runner.call_args.args[0]
        self.assertEqual(command[0:6], ("/bin/codex", "exec", "--json", "--sandbox", "read-only", "--ephemeral"))
        self.assertEqual(command[-1], providers.SECURITY_PREAMBLE + "do work")

    def test_timeout_returns_a_normalized_result(self) -> None:
        result = providers.execute_provider(
            providers.ProviderRequest("do work", timeout_seconds=2),
            which=lambda _: "/bin/codex",
            runner=Mock(side_effect=subprocess.TimeoutExpired("codex", 2)),
        )
        self.assertEqual((result.status, result.provider), ("timed_out", "codex"))

    def test_provider_environment_does_not_share_known_credentials(self) -> None:
        runner = Mock(return_value=subprocess.CompletedProcess([], 0, "done", ""))
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "openai",
                "ANTHROPIC_API_KEY": "anthropic",
                "CODEX_API_KEY": "codex",
                "AWS_SECRET_ACCESS_KEY": "aws-secret",
                "GH_TOKEN": "github-secret",
                "SSH_AUTH_SOCK": "/tmp/agent.sock",
                "PATH": ".:/tmp:/usr/bin",
            },
        ):
            providers.execute_provider(
                providers.ProviderRequest("do work", preferred_provider="claude"),
                which=lambda name: "/bin/claude" if name == "claude" else None,
                runner=runner,
            )
        environment = runner.call_args.kwargs["env"]
        self.assertNotIn("OPENAI_API_KEY", environment)
        self.assertNotIn("CODEX_API_KEY", environment)
        self.assertEqual("anthropic", environment["ANTHROPIC_API_KEY"])
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", environment)
        self.assertNotIn("GH_TOKEN", environment)
        self.assertNotIn("SSH_AUTH_SOCK", environment)
        self.assertEqual("/usr/bin", environment["PATH"])

    def test_receipt_hashes_secrets_without_persisting_them(self) -> None:
        request = providers.ProviderRequest("token=secret")
        result = providers.ProviderResult("completed", "codex", "codex", False, 0, "answer=secret", None, {"leaked": "secret"})
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "receipt.jsonl"
            providers.append_proof_receipt(receipt, request, result)
            text = receipt.read_text(encoding="utf-8")
        self.assertNotIn("secret", text)
        receipt_data = json.loads(text)
        self.assertEqual(receipt_data["prompt_hash"], providers._hash("token=secret"))
        self.assertEqual(receipt_data["status"], "completed")
        self.assertEqual(receipt_data["provider"], "codex")
        self.assertEqual(receipt_data["requested_provider"], "codex")
        self.assertFalse(receipt_data["fallback_used"])
        self.assertEqual(receipt_data["exit_code"], 0)
        self.assertEqual(receipt_data["timeout_seconds"], 300)

    def test_receipt_uses_typed_result_fields_when_receipt_data_is_empty(self) -> None:
        request = providers.ProviderRequest("do work", preferred_provider="claude", timeout_seconds=7)
        result = providers.ProviderResult("failed", "claude", "claude", False, 2, "", "failed", {})
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "receipt.jsonl"
            providers.append_proof_receipt(receipt, request, result)
            row = json.loads(receipt.read_text(encoding="utf-8"))
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["provider"], "claude")
        self.assertEqual(row["requested_provider"], "claude")
        self.assertFalse(row["fallback_used"])
        self.assertEqual(row["exit_code"], 2)
        self.assertEqual(row["timeout_seconds"], 7)

    def test_codex_write_access_is_explicit_and_sandboxed(self) -> None:
        runner = Mock(return_value=subprocess.CompletedProcess([], 0, "done", ""))
        providers.execute_provider(
            providers.ProviderRequest("do work", write_access=True),
            which=lambda _: "/bin/codex",
            runner=runner,
        )
        command = runner.call_args.args[0]
        self.assertIn("workspace-write", command)
        self.assertNotIn("danger-full-access", command)
        self.assertIn("--ignore-user-config", command)
        self.assertIn("--ignore-rules", command)
        self.assertIn("project_doc_max_bytes=0", command)
        self.assertIn('approval_policy="never"', command)
        self.assertIn("sandbox_workspace_write.network_access=false", command)
        self.assertIn('shell_environment_policy.inherit="none"', command)
        self.assertIn("allow_login_shell=false", command)

    def test_claude_uses_plan_or_isolated_edit_permissions(self) -> None:
        runner = Mock(return_value=subprocess.CompletedProcess([], 0, "done", ""))
        for write_access, expected in ((False, "plan"), (True, "acceptEdits")):
            providers.execute_provider(
                providers.ProviderRequest("do work", preferred_provider="claude", write_access=write_access),
                which=lambda _: "/bin/claude",
                runner=runner,
            )
            command = runner.call_args.args[0]
            self.assertIn(expected, command)
            self.assertIn("--safe-mode", command)
            self.assertIn("--strict-mcp-config", command)
            self.assertIn("--no-session-persistence", command)
            self.assertIn("--no-chrome", command)
            self.assertIn("--disable-slash-commands", command)
            denied = command[command.index("--disallowedTools") + 1 : command.index("--tools")]
            self.assertEqual(("WebFetch", "WebSearch", "mcp__*"), denied)
            tools = command[command.index("--tools") + 1]
            self.assertEqual("Read,Edit,Write,Grep,Glob" if write_access else "Read,Grep,Glob", tools)
            self.assertNotIn("Bash", tools)
            self.assertEqual("8", command[command.index("--max-turns") + 1])

    def test_request_limits_are_enforced_before_execution(self) -> None:
        runner = Mock()
        with self.assertRaises(ValueError):
            providers.execute_provider(
                providers.ProviderRequest("x" * (providers.MAX_PROMPT_CHARS + 1)),
                which=lambda _: "/bin/codex",
                runner=runner,
            )
        runner.assert_not_called()

    def test_provider_output_is_bounded(self) -> None:
        completed = providers._run_bounded(
            (sys.executable, "-c", "import sys; sys.stdout.write('x' * 2000000)"),
            cwd=None,
            env=os.environ.copy(),
            timeout=5,
        )
        self.assertEqual(125, completed.returncode)
        self.assertLessEqual(len(completed.stdout.encode("utf-8")), providers.MAX_PROVIDER_OUTPUT_BYTES)
        self.assertIn("output exceeded", completed.stderr)

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

    def test_recovery_can_reuse_only_the_expected_registered_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            worktrees = root / "worktrees"
            subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "CodeCanopy Test"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
            (repo / "seed.txt").write_text("seed", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "seed.txt"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-m", "seed"], check=True, capture_output=True)
            revision = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            target = providers.prepare_isolated_worktree(repo, worktrees, "worker-a", revision=revision)
            reused = providers.prepare_isolated_worktree(
                repo, worktrees, "worker-a", revision=revision, reuse_existing=True
            )
        self.assertEqual(target.resolve(), reused)

    def test_recovery_rejects_a_forged_git_marker(self) -> None:
        runner = Mock(side_effect=subprocess.CalledProcessError(128, ["git"]))
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "worker-a"
            target.mkdir()
            (target / ".git").write_text("gitdir: /tmp/forged", encoding="utf-8")
            with self.assertRaises(subprocess.CalledProcessError):
                providers.prepare_isolated_worktree(
                    ".", directory, "worker-a", reuse_existing=True, runner=runner
                )

    def test_receipt_rejects_a_symlink(self) -> None:
        request = providers.ProviderRequest("do work")
        result = providers.ProviderResult("completed", "codex", "codex", False, 0, "ok", None, {})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.write_text("untouched", encoding="utf-8")
            receipt = root / "receipt.jsonl"
            receipt.symlink_to(target)
            with self.assertRaises(ValueError):
                providers.append_proof_receipt(receipt, request, result)
            self.assertEqual("untouched", target.read_text(encoding="utf-8"))

    def test_receipt_rejects_a_hard_link(self) -> None:
        request = providers.ProviderRequest("do work")
        result = providers.ProviderResult("completed", "codex", "codex", False, 0, "ok", None, {})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.write_text("untouched", encoding="utf-8")
            receipt = root / "receipt.jsonl"
            os.link(target, receipt)
            with self.assertRaises(ValueError):
                providers.append_proof_receipt(receipt, request, result)
            self.assertEqual("untouched", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
