from __future__ import annotations

import json
from hashlib import sha256
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
        with patch.object(providers, "_run_bounded") as runner:
            result = providers.execute_provider(
                providers.ProviderRequest("do work", preferred_provider="claude"),
                which=lambda name: "/bin/codex" if name == "codex" else None,
            )
        self.assertEqual((result.status, result.provider, result.fallback_used), ("unavailable", None, False))
        runner.assert_not_called()

    def test_claude_fallback_to_codex_requires_explicit_opt_in(self) -> None:
        with patch.object(
            providers, "_run_bounded", return_value=subprocess.CompletedProcess([], 0, "done", "")
        ) as runner:
            result = providers.execute_provider(
                providers.ProviderRequest("do work", preferred_provider="claude", allow_fallback=True),
                which=lambda name: "/bin/codex" if name == "codex" else None,
            )
        self.assertEqual((result.status, result.provider, result.fallback_used), ("completed", "codex", True))
        self.assertEqual(result.receipt_data["fallback_reason"], "preferred provider executable unavailable")
        command = runner.call_args.args[0]
        self.assertEqual(command[0:6], ("/bin/codex", "exec", "--json", "--sandbox", "read-only", "--ephemeral"))
        self.assertEqual(command[-1], providers.SECURITY_PREAMBLE + "do work")

    def test_claude_fallback_rejects_provider_specific_settings(self) -> None:
        which = Mock(return_value=None)
        with patch.object(providers, "_run_bounded") as runner:
            with self.assertRaisesRegex(ValueError, "fallback"):
                providers.execute_provider(
                    providers.ProviderRequest(
                        "do work",
                        preferred_provider="claude",
                        allow_fallback=True,
                        model="sonnet",
                        reasoning_effort="high",
                    ),
                    which=which,
                )
        runner.assert_not_called()
        which.assert_called_once_with("claude")

    def test_codex_command_includes_trusted_model_and_effort_before_prompt(self) -> None:
        completed = subprocess.CompletedProcess([], 0, '{"type":"turn.completed","usage":{}}\n', "")
        with patch.object(providers, "_run_bounded", return_value=completed) as runner:
            providers.execute_provider(
                providers.ProviderRequest(
                    "review",
                    model="gpt-5.6-luna",
                    reasoning_effort="medium",
                ),
                which=lambda _: "/bin/codex",
            )
        command = runner.call_args.args[0]
        self.assertEqual("/bin/codex", command[0])
        self.assertEqual("gpt-5.6-luna", command[command.index("--model") + 1])
        self.assertIn('model_reasoning_effort="medium"', command)
        self.assertEqual(providers.SECURITY_PREAMBLE + "review", command[-1])

    def test_invalid_or_unsupported_model_settings_fail_before_execution(self) -> None:
        requests = (
            providers.ProviderRequest("review", model="../../escape"),
            providers.ProviderRequest("review", reasoning_effort="fast"),
            providers.ProviderRequest("review", preferred_provider="claude", reasoning_effort="ultra"),
        )
        for request in requests:
            with self.subTest(request=request), patch.object(providers, "_run_bounded") as runner:
                with self.assertRaises(ValueError):
                    providers.execute_provider(request, which=lambda _: "/bin/provider")
                runner.assert_not_called()

    def test_claude_command_includes_selected_model_and_effort(self) -> None:
        request = providers.ProviderRequest(
            "review",
            preferred_provider="claude",
            model="sonnet",
            reasoning_effort="high",
            model_catalog_hash="a" * 64,
        )
        completed = subprocess.CompletedProcess([], 0, '{"modelUsage":{"claude-sonnet-current":{}}}', "")
        with patch.object(providers, "_run_bounded", return_value=completed) as runner:
            result = providers.execute_provider(request, which=lambda _: "/bin/claude")
        command = runner.call_args.args[0]
        self.assertEqual(("--model", "sonnet", "--effort", "high"), command[-5:-1])
        self.assertEqual(providers.SECURITY_PREAMBLE + "review", command[-1])
        self.assertEqual("claude-sonnet-current", result.actual_model)
        with tempfile.TemporaryDirectory() as directory:
            receipt_path = Path(directory) / "receipt.jsonl"
            providers.append_proof_receipt(receipt_path, request, result)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual("claude-sonnet-current", receipt["actual_model"])
        self.assertEqual("a" * 64, receipt["model_catalog_hash"])

    def test_claude_actual_model_requires_one_valid_model_usage_key(self) -> None:
        request = providers.ProviderRequest("review", preferred_provider="claude")
        for output in ("not JSON", '{"modelUsage":{"one":{},"two":{}}}', '{"modelUsage":{"../escape":{}}}'):
            with self.subTest(output=output):
                result = providers._result(
                    status="completed",
                    provider="claude",
                    request=request,
                    fallback_used=False,
                    output=output,
                )
                self.assertIsNone(result.actual_model)

    def test_claude_actual_model_rejects_duplicate_model_usage_members(self) -> None:
        result = providers._result(
            status="completed",
            provider="claude",
            request=providers.ProviderRequest("review", preferred_provider="claude"),
            fallback_used=False,
            output='{"modelUsage":{"claude-sonnet-current":{}},"modelUsage":{"claude-opus-current":{}}}',
        )
        self.assertIsNone(result.actual_model)

    def test_invalid_model_catalog_hash_fails_before_execution(self) -> None:
        for catalog_hash in ("A" * 64, "a" * 63, "g" * 64):
            with self.subTest(catalog_hash=catalog_hash), patch.object(providers, "_run_bounded") as runner:
                with self.assertRaisesRegex(ValueError, "lowercase SHA-256 digest"):
                    providers.execute_provider(
                        providers.ProviderRequest("review", model_catalog_hash=catalog_hash),
                        which=lambda _: "/bin/codex",
                    )
                runner.assert_not_called()

    def test_catalog_snapshot_rejects_unbound_dispatch_settings_before_execution(self) -> None:
        roles = {
            "lead": {"model": "codex-lead", "reasoning_effort": "high"},
            "expert": {"model": "codex-expert", "reasoning_effort": "high"},
            "reviewer": {"model": "codex-expert", "reasoning_effort": "high"},
            "worker": {"model": "codex-worker", "reasoning_effort": "medium"},
        }
        payload = {
            "provider": "codex",
            "source": "test_catalog",
            "source_version": "1",
            "roles": roles,
        }
        catalog_hash = sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        snapshot = {**payload, "catalog_hash": catalog_hash}
        requests = (
            providers.ProviderRequest(
                "review",
                model="codex-unlisted",
                reasoning_effort="high",
                model_catalog_hash=catalog_hash,
                model_catalog_snapshot=snapshot,
            ),
            providers.ProviderRequest(
                "review",
                model_catalog_hash=catalog_hash,
                model_catalog_snapshot=snapshot,
            ),
        )
        for request in requests:
            with self.subTest(request=request), patch.object(providers, "_run_bounded") as runner:
                with self.assertRaisesRegex(ValueError, "must match the model catalog snapshot"):
                    providers.execute_provider(request, which=lambda _: "/bin/codex")
                runner.assert_not_called()
        exact = providers.ProviderRequest(
            "review",
            model="codex-lead",
            reasoning_effort="high",
            model_catalog_hash=catalog_hash,
            model_catalog_snapshot=snapshot,
        )
        completed = subprocess.CompletedProcess([], 0, '{"type":"turn.completed","usage":{}}\n', "")
        with patch.object(providers, "_run_bounded", return_value=completed) as runner:
            providers.execute_provider(exact, which=lambda _: "/bin/codex")
        runner.assert_called_once()

    def test_timeout_returns_a_normalized_result(self) -> None:
        with patch.object(providers, "_run_bounded", side_effect=subprocess.TimeoutExpired("codex", 2)):
            result = providers.execute_provider(
                providers.ProviderRequest("do work", timeout_seconds=2),
                which=lambda _: "/bin/codex",
            )
        self.assertEqual((result.status, result.provider), ("timed_out", "codex"))

    def test_provider_environment_does_not_share_known_credentials(self) -> None:
        with patch.object(
            providers, "_run_bounded", return_value=subprocess.CompletedProcess([], 0, "done", "")
        ) as runner, patch.dict(
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
        request = providers.ProviderRequest("token=secret", model="gpt-5.6-luna", reasoning_effort="medium")
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
        self.assertEqual("gpt-5.6-luna", receipt_data["requested_model"])
        self.assertEqual("medium", receipt_data["requested_reasoning_effort"])

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
        with patch.object(
            providers, "_run_bounded", return_value=subprocess.CompletedProcess([], 0, "done", "")
        ) as runner:
            providers.execute_provider(
                providers.ProviderRequest("do work", write_access=True),
                which=lambda _: "/bin/codex",
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
        with patch.object(
            providers, "_run_bounded", return_value=subprocess.CompletedProcess([], 0, "done", "")
        ) as runner:
            for write_access, expected in ((False, "plan"), (True, "acceptEdits")):
                providers.execute_provider(
                    providers.ProviderRequest("do work", preferred_provider="claude", write_access=write_access),
                    which=lambda _: "/bin/claude",
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
        with patch.object(providers, "_run_bounded") as runner, self.assertRaises(ValueError):
            providers.execute_provider(
                providers.ProviderRequest("x" * (providers.MAX_PROMPT_CHARS + 1)),
                which=lambda _: "/bin/codex",
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

    def test_provider_streams_are_closed_after_capture(self) -> None:
        original_popen = subprocess.Popen
        processes = []

        def capture_process(*args, **kwargs):
            process = original_popen(*args, **kwargs)
            processes.append(process)
            return process

        with patch.object(providers.subprocess, "Popen", side_effect=capture_process):
            providers._run_bounded(
                (sys.executable, "-c", "print('done')"),
                cwd=None,
                env=os.environ.copy(),
                timeout=5,
            )

        self.assertTrue(processes[0].stdout.closed)
        self.assertTrue(processes[0].stderr.closed)

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
        self.assertEqual(providers.GIT_OPERATION_TIMEOUT_SECONDS, runner.call_args.kwargs["timeout"])

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

    def test_receipt_append_rejects_the_event_after_the_limit(self) -> None:
        request = providers.ProviderRequest("do work")
        result = providers.ProviderResult("completed", "codex", "codex", False, 0, "ok", None, {})
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "receipt.jsonl"
            providers.append_proof_receipt(receipt, request, result)
            original = receipt.read_bytes()
            with patch.object(providers, "MAX_RECEIPT_EVENTS", 1), self.assertRaisesRegex(
                ValueError, "event limit"
            ):
                providers.append_proof_receipt(receipt, request, result)
            self.assertEqual(original, receipt.read_bytes())

    def test_receipt_append_rejects_an_existing_oversized_file_before_scanning(self) -> None:
        request = providers.ProviderRequest("do work")
        result = providers.ProviderResult("completed", "codex", "codex", False, 0, "ok", None, {})
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "receipt.jsonl"
            receipt.write_bytes(b"x" * 9)
            original = receipt.read_bytes()
            with patch.object(providers, "MAX_RECEIPT_BYTES", 8), self.assertRaisesRegex(
                ValueError, "size limit"
            ):
                providers.append_proof_receipt(receipt, request, result)
            self.assertEqual(original, receipt.read_bytes())


if __name__ == "__main__":
    unittest.main()
