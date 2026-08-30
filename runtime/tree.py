"""Small mixed-provider tree runner backed by the provider and manifest contracts."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import subprocess
from typing import Callable, Iterable, Mapping, Sequence

from .manifest import ManifestError, ManifestStore
from .safeio import read_regular_limited
from .providers import (
    ProviderName,
    ProviderRequest,
    ProviderResult,
    MAX_PROMPT_CHARS,
    MAX_TIMEOUT_SECONDS,
    append_proof_receipt,
    execute_provider,
    prepare_isolated_worktree,
)


_NODE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_RUN_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_IMMUTABLE_COMMIT = re.compile(r"^[0-9a-fA-F]{40,64}$")
MAX_PLAN_BYTES = 1024 * 1024
MAX_NODES = 9
MAX_DEPTH = 3
MAX_DEPENDENCIES = 3


@dataclass(frozen=True)
class TreeNode:
    node_id: str
    prompt: str
    provider: ProviderName = "codex"
    depends_on: tuple[str, ...] = ()
    baseline: str = "HEAD"
    dependency_commits: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: float = 300
    worktree_name: str | None = None

    def __post_init__(self) -> None:
        if not self.node_id or len(self.node_id) > 64 or not _NODE_ID.fullmatch(self.node_id):
            raise ValueError("node_id must contain 1-64 letters, numbers, '.', '_' or '-'")
        if not self.prompt.strip() or len(self.prompt) > MAX_PROMPT_CHARS:
            raise ValueError(f"prompt must contain 1-{MAX_PROMPT_CHARS} characters")
        if self.provider not in ("codex", "claude"):
            raise ValueError(f"unsupported provider: {self.provider}")
        if not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= MAX_TIMEOUT_SECONDS:
            raise ValueError(f"timeout_seconds must be between 0 and {MAX_TIMEOUT_SECONDS}")
        if len(self.depends_on) > MAX_DEPENDENCIES or len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError(f"depends_on must contain at most {MAX_DEPENDENCIES} unique nodes")
        if not self.baseline.strip():
            raise ValueError("baseline must not be empty")
        if set(self.dependency_commits) != set(self.depends_on):
            raise ValueError("dependency_commits must exactly cover depends_on")
        if any(not _IMMUTABLE_COMMIT.fullmatch(commit) for commit in self.dependency_commits.values()):
            raise ValueError("dependency_commits must be immutable commit ids")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "TreeNode":
        node_id = value.get("id")
        prompt = value.get("prompt")
        provider = value.get("provider", "codex")
        baseline = value.get("baseline", "HEAD")
        timeout = value.get("timeout_seconds", 300)
        worktree_name = value.get("worktree_name")
        if not isinstance(node_id, str) or not isinstance(prompt, str):
            raise ValueError("node id and prompt must be strings")
        if not isinstance(provider, str) or not isinstance(baseline, str):
            raise ValueError("provider and baseline must be strings")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise ValueError("timeout_seconds must be a number")
        if worktree_name is not None and not isinstance(worktree_name, str):
            raise ValueError("worktree_name must be a string")
        dependencies_value = value.get("depends_on", ())
        if not isinstance(dependencies_value, (list, tuple)) or not all(isinstance(item, str) for item in dependencies_value):
            raise ValueError("depends_on must be an array of strings")
        dependencies = tuple(dependencies_value)
        commits = value.get("dependency_commits", {})
        if not isinstance(commits, Mapping) or not all(isinstance(key, str) and isinstance(commit, str) for key, commit in commits.items()):
            raise ValueError("dependency_commits must be an object of strings")
        return cls(
            node_id=node_id,
            prompt=prompt,
            provider=provider,  # type: ignore[arg-type]
            depends_on=dependencies,
            baseline=baseline,
            dependency_commits=dict(commits),
            timeout_seconds=float(timeout),
            worktree_name=worktree_name,
        )


def run_tree(
    nodes: Iterable[TreeNode],
    *,
    manifest_path: str | Path,
    run_id: str,
    repo: str | Path | None = None,
    worktree_root: str | Path | None = None,
    receipt_dir: str | Path | None = None,
    execute: Callable[[ProviderRequest], ProviderResult] = execute_provider,
    prepare: Callable[..., Path] = prepare_isolated_worktree,
    accept: Callable[[TreeNode, ProviderResult], bool] | None = None,
    allow_provider_fallback: bool = False,
) -> dict[str, object]:
    """Run ready nodes in dependency order and leave resume evidence in JSONL."""
    ordered = _topological(tuple(nodes))
    _validate_run_id(run_id)
    if worktree_root is not None and repo is None:
        raise ValueError("repo is required when worktree_root is provided")
    store = ManifestStore(manifest_path)
    try:
        snapshot = store.snapshot(run_id)
    except ManifestError:
        store.create_run(run_id, state="planned", repo=str(repo) if repo else None)
        snapshot = store.snapshot(run_id)
    if any(node["state"] == "accepted" for node in snapshot["nodes"].values()):
        raise ManifestError("accepted manifest state cannot be resumed; start a new run after reviewing evidence")

    recovered = store.recover_interrupted(run_id)
    store.set_run_state(run_id, "active")
    snapshot = store.snapshot(run_id)
    known = set(snapshot["nodes"])
    resolved_baselines = {
        node.node_id: _resolve_baseline(node.baseline, repo)
        for node in ordered
    }
    repository = Path(repo) if repo is not None else Path.cwd()
    for node in ordered:
        _verify_dependency_commits(node, resolved_baselines[node.node_id], repository)
    for node in ordered:
        baseline = resolved_baselines[node.node_id]
        if node.node_id in known:
            _verify_saved_contract(snapshot["nodes"][node.node_id], node, baseline)
            continue
        store.record_node(
            run_id,
            node.node_id,
            state="ready",
            dependencies=node.depends_on,
            baseline={"commit": baseline, "dependency_commits": dict(node.dependency_commits)},
            prompt_hash=_prompt_hash(node.prompt),
            provider=node.provider,
            timeout_seconds=node.timeout_seconds,
            worktree_name=node.worktree_name,
        )
    receipts = Path(receipt_dir) if receipt_dir else Path(manifest_path).parent / "receipts"
    summaries: dict[str, dict[str, object]] = {}
    for node in ordered:
        snapshot = store.snapshot(run_id)
        current = snapshot["nodes"][node.node_id]
        if current["state"] == "accepted":
            summaries[node.node_id] = {"status": "accepted", "provider": node.provider}
            continue
        if current["state"] not in {"draft", "planned", "ready"}:
            summaries[node.node_id] = {"status": current["state"], "provider": node.provider}
            continue
        dependency_states = {dep: snapshot["nodes"][dep]["state"] for dep in node.depends_on}
        if any(state != "accepted" for state in dependency_states.values()):
            summaries[node.node_id] = {"status": "ready", "reason": "dependency not accepted"}
            continue

        store.set_node_state(run_id, node.node_id, "active")
        cwd = Path(repo).resolve() if repo is not None else Path.cwd().resolve()
        if worktree_root is not None and repo is not None:
            prepare_kwargs = {"revision": resolved_baselines[node.node_id]}
            if node.node_id in recovered:
                prepare_kwargs["reuse_existing"] = True
            cwd = prepare(repo, worktree_root, node.worktree_name or node.node_id, **prepare_kwargs)
        request = ProviderRequest(
            prompt=node.prompt,
            preferred_provider=node.provider,
            timeout_seconds=node.timeout_seconds,
            cwd=cwd,
            allow_fallback=allow_provider_fallback,
            write_access=worktree_root is not None,
        )
        result = execute(request)
        receipt_path = receipts / f"{node.node_id}.jsonl"
        append_proof_receipt(
            receipt_path,
            request,
            result,
            run_id=run_id,
            node_id=node.node_id,
            baseline=resolved_baselines[node.node_id],
        )
        store.record_check(run_id, node.node_id, "provider invocation", result.status, evidence=str(receipt_path))
        store.set_node_state(run_id, node.node_id, "returned")
        accepted = result.status == "completed" and accept is not None and accept(node, result)
        if accepted:
            store.set_node_state(run_id, node.node_id, "accepted")
        elif result.status != "completed":
            store.set_node_state(run_id, node.node_id, "blocked")
        summaries[node.node_id] = {
            "status": "accepted" if accepted else ("blocked" if result.status != "completed" else "returned"),
            "provider_status": result.status,
            "requested_provider": result.requested_provider,
            "provider": result.provider,
            "fallback_used": result.fallback_used,
            "receipt": str(receipt_path),
        }
    final = store.snapshot(run_id)
    states = {node["state"] for node in final["nodes"].values()}
    if states and states <= {"accepted"}:
        run_state = "completed"
    elif "blocked" in states or "invalidated" in states:
        run_state = "blocked"
    else:
        run_state = "planned"
    store.set_run_state(run_id, run_state)
    return {"run_id": run_id, "recovered": recovered, "nodes": summaries, "state": run_state}


def _resolve_baseline(revision: str, repo: str | Path | None) -> str:
    """Resolve symbolic revisions once so every manifest record is immutable."""
    location = Path(repo) if repo is not None else Path.cwd()
    try:
        completed = subprocess.run(
            ["git", "-C", str(location.resolve()), "rev-parse", "--verify", f"{revision}^{{commit}}"],
            capture_output=True,
            check=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise ManifestError(f"could not resolve immutable baseline {revision!r} in {location}") from error
    commit = completed.stdout.strip()
    if not _IMMUTABLE_COMMIT.fullmatch(commit):
        raise ManifestError(f"git returned a non-immutable baseline for {revision!r}")
    return commit.lower()


def _verify_saved_contract(current: Mapping[str, object], node: TreeNode, baseline: str) -> None:
    """Reject a same-ID redispatch when its recorded execution contract changed."""
    details = current.get("details", {})
    if not isinstance(details, Mapping):
        raise ManifestError(f"node {node.node_id} has an invalid saved contract")
    expected = {
        "prompt_hash": _prompt_hash(node.prompt),
        "provider": node.provider,
        "timeout_seconds": node.timeout_seconds,
        "worktree_name": node.worktree_name,
    }
    actual = {key: details.get(key) for key in expected}
    actual["dependencies"] = current.get("dependencies")
    expected["dependencies"] = list(node.depends_on)
    actual["baseline"] = current.get("baseline")
    expected["baseline"] = {
        "commit": baseline,
        "dependency_commits": dict(sorted(node.dependency_commits.items())),
    }
    if actual != expected:
        raise ManifestError(f"saved contract for node {node.node_id} does not match the requested plan")


def _topological(nodes: Sequence[TreeNode]) -> list[TreeNode]:
    if not nodes or len(nodes) > MAX_NODES:
        raise ValueError(f"tree must contain 1-{MAX_NODES} nodes")
    by_id = {node.node_id: node for node in nodes}
    if len(by_id) != len(nodes):
        raise ValueError("node ids must be unique")
    for node in nodes:
        unknown = set(node.depends_on) - set(by_id)
        if unknown:
            raise ValueError(f"{node.node_id} depends on unknown nodes: {', '.join(sorted(unknown))}")
    result: list[TreeNode] = []
    pending = list(nodes)
    accepted: set[str] = set()
    depths: dict[str, int] = {}
    while pending:
        ready = [node for node in pending if set(node.depends_on) <= accepted]
        if not ready:
            raise ValueError("node dependencies contain a cycle")
        for node in ready:
            depth = 0 if not node.depends_on else 1 + max(depths[dependency] for dependency in node.depends_on)
            if depth > MAX_DEPTH:
                raise ValueError(f"node {node.node_id} exceeds maximum dependency depth {MAX_DEPTH}")
            depths[node.node_id] = depth
        result.extend(ready)
        accepted.update(node.node_id for node in ready)
        pending = [node for node in pending if node not in ready]
    return result


def _load_plan(path: Path) -> tuple[str, list[TreeNode]]:
    payload = read_regular_limited(path, MAX_PLAN_BYTES)
    if len(payload) > MAX_PLAN_BYTES:
        raise ValueError(f"plan exceeds {MAX_PLAN_BYTES} bytes")
    data = json.loads(payload.decode("utf-8"))
    if not isinstance(data, Mapping) or "nodes" not in data:
        raise ValueError("plan must be an object containing nodes")
    unknown = set(data) - {"run_id", "nodes"}
    if unknown:
        raise ValueError(f"untrusted plan options are not allowed: {', '.join(sorted(unknown))}")
    values = data["nodes"]
    if not isinstance(values, list) or not all(isinstance(value, Mapping) for value in values):
        raise ValueError("nodes must be an array of objects")
    run_id = data.get("run_id", path.stem)
    if not isinstance(run_id, str):
        raise ValueError("run_id must be a string")
    _validate_run_id(run_id)
    return run_id, [TreeNode.from_mapping(value) for value in values]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a bounded CodeCanopy provider tree")
    parser.add_argument("plan", type=Path, nargs="?", help="JSON plan containing run_id and nodes")
    parser.add_argument("--manifest", type=Path, required=True, help="append-only JSONL manifest path")
    parser.add_argument("--run-id", help="run identifier for --status or --inspect")
    parser.add_argument("--repo", type=Path, help="trusted repository root; never read from the plan")
    parser.add_argument("--worktree-root", type=Path, help="trusted isolated-worktree root")
    parser.add_argument("--receipt-dir", type=Path, help="trusted private receipt directory")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--status", action="store_true", help="show run state and dependency-ready frontier")
    action.add_argument("--inspect", metavar="NODE_ID", help="show one recorded node contract and evidence")
    parser.add_argument("--accept-completed", action="store_true", help="use successful CLI exit as this run's explicit leaf check")
    parser.add_argument("--allow-provider-fallback", action="store_true", help="allow unavailable Claude nodes to run with Codex")
    args = parser.parse_args(argv)
    if args.status or args.inspect:
        if args.plan is not None or not args.run_id:
            parser.error("--status/--inspect require --manifest and --run-id without a plan")
        store = ManifestStore(args.manifest)
        payload = store.status(args.run_id) if args.status else store.inspect_node(args.run_id, args.inspect)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.plan is None:
        parser.error("a plan is required unless --status or --inspect is used")
    run_id, nodes = _load_plan(args.plan)
    accept = (lambda _node, result: result.status == "completed") if args.accept_completed else None
    print(
        json.dumps(
            run_tree(
                nodes,
                manifest_path=args.manifest,
                run_id=run_id,
                repo=args.repo,
                worktree_root=args.worktree_root,
                receipt_dir=args.receipt_dir,
                accept=accept,
                allow_provider_fallback=args.allow_provider_fallback,
            ),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _validate_run_id(run_id: str) -> None:
    if not run_id or len(run_id) > 64 or not _RUN_ID.fullmatch(run_id):
        raise ValueError("run_id must contain 1-64 letters, numbers, '.', '_' or '-'")


def _prompt_hash(prompt: str) -> str:
    return sha256(prompt.encode("utf-8")).hexdigest()


def _verify_dependency_commits(node: TreeNode, baseline: str, repo: Path) -> None:
    for dependency, commit in node.dependency_commits.items():
        resolved = _resolve_baseline(commit, repo)
        if resolved != commit.lower():
            raise ManifestError(f"dependency commit for {dependency} did not resolve exactly")
        try:
            subprocess.run(
                ["git", "-C", str(repo.resolve()), "merge-base", "--is-ancestor", resolved, baseline],
                capture_output=True,
                check=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            raise ManifestError(f"baseline for {node.node_id} does not contain dependency {dependency}") from error


if __name__ == "__main__":
    raise SystemExit(main())
