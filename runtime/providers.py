"""Small, headless execution adapters for installed Codex and Claude CLIs.

Commands are intentionally configurable per request.  The defaults are
``codex exec --skip-git-repo-check --json`` and ``claude --print
--output-format json``; the prompt is appended as one argument, never
interpolated into a shell command.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path, PurePath
import shutil
import subprocess
from typing import Callable, Literal, Mapping, Sequence


ProviderName = Literal["codex", "claude"]
ResultStatus = Literal["completed", "failed", "timed_out", "unavailable"]
DEFAULT_COMMANDS: Mapping[ProviderName, tuple[str, ...]] = {
    "codex": ("codex", "exec", "--skip-git-repo-check", "--json"),
    "claude": ("claude", "--print", "--output-format", "json"),
}


@dataclass(frozen=True)
class ProviderRequest:
    prompt: str
    preferred_provider: ProviderName = "codex"
    timeout_seconds: float = 300
    cwd: str | Path | None = None
    command_overrides: Mapping[ProviderName, Sequence[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderCapability:
    provider: ProviderName
    available: bool
    executable: str | None
    version: str | None = None


@dataclass(frozen=True)
class ProviderResult:
    status: ResultStatus
    provider: ProviderName | None
    requested_provider: ProviderName
    fallback_used: bool
    exit_code: int | None
    output: str
    error: str | None
    receipt_data: Mapping[str, object]


def provider_capability(
    provider: ProviderName,
    *,
    probe_version: bool = False,
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> ProviderCapability:
    """Check local CLI availability; version probing is opt-in and bounded."""
    _validate_provider(provider)
    executable = which(provider)
    if not executable:
        return ProviderCapability(provider, False, None)
    if not probe_version:
        return ProviderCapability(provider, True, executable)
    try:
        completed = runner(
            [executable, "--version"],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ProviderCapability(provider, True, executable)
    version = (completed.stdout or completed.stderr or "").strip() or None
    return ProviderCapability(provider, True, executable, version)


def execute_provider(
    request: ProviderRequest,
    *,
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> ProviderResult:
    """Run one local provider, falling back from Claude to Codex explicitly."""
    _validate_provider(request.preferred_provider)
    selected = request.preferred_provider
    executable = which(selected)
    fallback_used = False
    fallback_reason: str | None = None
    if not executable and selected != "codex":
        selected, executable = "codex", which("codex")
        fallback_used = executable is not None
        fallback_reason = "preferred provider executable unavailable"
    if not executable:
        return _result(
            status="unavailable",
            provider=None,
            request=request,
            fallback_used=False,
            error="no supported provider executable is available",
            fallback_reason=fallback_reason,
        )

    command = tuple(request.command_overrides.get(selected, DEFAULT_COMMANDS[selected]))
    if not command:
        raise ValueError(f"empty command for {selected}")
    command = (executable, *command[1:], request.prompt)
    try:
        completed = runner(
            command,
            capture_output=True,
            check=False,
            cwd=str(request.cwd) if request.cwd else None,
            text=True,
            timeout=request.timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return _result(
            status="timed_out",
            provider=selected,
            request=request,
            fallback_used=fallback_used,
            error=f"provider timed out after {request.timeout_seconds:g} seconds",
            fallback_reason=fallback_reason,
        )
    except OSError as error:
        return _result(
            status="failed",
            provider=selected,
            request=request,
            fallback_used=fallback_used,
            error=str(error),
            fallback_reason=fallback_reason,
        )

    output = completed.stdout or ""
    error = (completed.stderr or "").strip() or None
    return _result(
        status="completed" if completed.returncode == 0 else "failed",
        provider=selected,
        request=request,
        fallback_used=fallback_used,
        exit_code=completed.returncode,
        output=output,
        error=error,
        fallback_reason=fallback_reason,
    )


def append_proof_receipt(path: str | Path, request: ProviderRequest, result: ProviderResult) -> None:
    """Append a JSONL receipt with hashes only; never persist prompt or output."""
    receipt = {
        key: result.receipt_data.get(key)
        for key in ("status", "provider", "requested_provider", "fallback_used", "fallback_reason", "exit_code", "timeout_seconds")
    }
    receipt.update(prompt_hash=_hash(request.prompt), output_hash=_hash(result.output))
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, sort_keys=True) + "\n")


def prepare_isolated_worktree(
    repo: str | Path,
    worktree_root: str | Path,
    name: str,
    *,
    revision: str = "HEAD",
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> Path:
    """Create a detached git worktree below a caller-owned root, never outside it."""
    relative = PurePath(name)
    if not name or relative.is_absolute() or ".." in relative.parts or str(relative) == ".":
        raise ValueError("worktree name must be a non-empty relative path without '..'")
    root = Path(worktree_root).resolve()
    target = (root / relative).resolve()
    try:
        target.relative_to(root)
    except ValueError as error:
        raise ValueError("worktree path escapes worktree root") from error
    if target.exists():
        raise FileExistsError(target)
    root.mkdir(parents=True, exist_ok=True)
    runner(
        ["git", "-C", str(Path(repo).resolve()), "worktree", "add", "--detach", str(target), revision],
        check=True,
        text=True,
        capture_output=True,
    )
    return target


def _result(
    *,
    status: ResultStatus,
    provider: ProviderName | None,
    request: ProviderRequest,
    fallback_used: bool,
    exit_code: int | None = None,
    output: str = "",
    error: str | None = None,
    fallback_reason: str | None = None,
) -> ProviderResult:
    receipt_data = {
        "status": status,
        "provider": provider,
        "requested_provider": request.preferred_provider,
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "exit_code": exit_code,
        "timeout_seconds": request.timeout_seconds,
        "prompt_hash": _hash(request.prompt),
        "output_hash": _hash(output),
    }
    return ProviderResult(status, provider, request.preferred_provider, fallback_used, exit_code, output, error, receipt_data)


def _hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _validate_provider(provider: str) -> None:
    if provider not in DEFAULT_COMMANDS:
        raise ValueError(f"unsupported provider: {provider}")
