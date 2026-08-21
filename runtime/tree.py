"""Small mixed-provider tree runner backed by the provider and manifest contracts."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Callable, Iterable, Mapping, Sequence

from .manifest import ManifestError, ManifestStore
from .providers import (
    ProviderName,
    ProviderRequest,
    ProviderResult,
    append_proof_receipt,
    execute_provider,
    prepare_isolated_worktree,
)


_NODE_ID = re.compile(r"^[A-Za-z0-9._-]+$")


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
        if not self.node_id or not _NODE_ID.fullmatch(self.node_id):
            raise ValueError("node_id must contain only letters, numbers, '.', '_' or '-'")
        if not self.prompt.strip():
            raise ValueError("prompt must not be empty")
        if self.provider not in ("codex", "claude"):
            raise ValueError(f"unsupported provider: {self.provider}")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "TreeNode":
        dependencies = tuple(str(item) for item in value.get("depends_on", ()))
        commits = value.get("dependency_commits", {})
        if not isinstance(commits, Mapping):
            raise ValueError("dependency_commits must be an object")
        return cls(
            node_id=str(value["id"]),
            prompt=str(value["prompt"]),
            provider=str(value.get("provider", "codex")),  # type: ignore[arg-type]
            depends_on=dependencies,
            baseline=str(value.get("baseline", "HEAD")),
            dependency_commits={str(key): str(commit) for key, commit in commits.items()},
            timeout_seconds=float(value.get("timeout_seconds", 300)),
            worktree_name=str(value["worktree_name"]) if value.get("worktree_name") else None,
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
) -> dict[str, object]:
    """Run ready nodes in dependency order and leave resume evidence in JSONL."""
    ordered = _topological(tuple(nodes))
    if worktree_root is not None and repo is None:
        raise ValueError("repo is required when worktree_root is provided")
    store = ManifestStore(manifest_path)
    try:
        snapshot = store.snapshot(run_id)
    except ManifestError:
        store.create_run(run_id, state="planned", repo=str(repo) if repo else None)
        snapshot = store.snapshot(run_id)

    recovered = store.recover_interrupted(run_id)
    snapshot = store.snapshot(run_id)
    known = set(snapshot["nodes"])
    for node in ordered:
        if node.node_id in known:
            continue
        store.record_node(
            run_id,
            node.node_id,
            state="ready",
            dependencies=node.depends_on,
            baseline={"commit": node.baseline, "dependency_commits": dict(node.dependency_commits)},
            provider=node.provider,
            timeout_seconds=node.timeout_seconds,
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
            store.set_node_state(run_id, node.node_id, "blocked")
            summaries[node.node_id] = {"status": "blocked", "reason": "dependency not accepted"}
            continue

        store.set_node_state(run_id, node.node_id, "active")
        cwd: Path | None = None
        if worktree_root is not None and repo is not None:
            cwd = prepare(repo, worktree_root, node.worktree_name or node.node_id, revision=node.baseline)
        result = execute(
            ProviderRequest(
                prompt=node.prompt,
                preferred_provider=node.provider,
                timeout_seconds=node.timeout_seconds,
                cwd=cwd,
            )
        )
        receipt_path = receipts / f"{node.node_id}.jsonl"
        append_proof_receipt(receipt_path, ProviderRequest(node.prompt, node.provider, node.timeout_seconds, cwd), result)
        store.record_check(run_id, node.node_id, "provider invocation", result.status, evidence=str(receipt_path))
        store.set_node_state(run_id, node.node_id, "returned")
        accepted = result.status == "completed" and accept is not None and accept(node, result)
        if accepted:
            store.set_node_state(run_id, node.node_id, "accepted")
        else:
            store.set_node_state(run_id, node.node_id, "blocked" if result.status != "completed" else "returned")
        summaries[node.node_id] = {
            "status": "accepted" if accepted else ("blocked" if result.status != "completed" else "returned"),
            "provider_status": result.status,
            "requested_provider": result.requested_provider,
            "provider": result.provider,
            "fallback_used": result.fallback_used,
            "receipt": str(receipt_path),
        }
    return {"run_id": run_id, "recovered": recovered, "nodes": summaries}


def _topological(nodes: Sequence[TreeNode]) -> list[TreeNode]:
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
    while pending:
        ready = [node for node in pending if set(node.depends_on) <= accepted]
        if not ready:
            raise ValueError("node dependencies contain a cycle")
        result.extend(ready)
        accepted.update(node.node_id for node in ready)
        pending = [node for node in pending if node not in ready]
    return result


def _load_plan(path: Path) -> tuple[str, list[TreeNode], dict[str, object]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping) or "nodes" not in data:
        raise ValueError("plan must be an object containing nodes")
    nodes = [TreeNode.from_mapping(value) for value in data["nodes"]]
    options = {key: data[key] for key in ("repo", "worktree_root", "receipt_dir") if key in data}
    return str(data.get("run_id", path.stem)), nodes, options


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a bounded CodeCanopy provider tree")
    parser.add_argument("plan", type=Path, help="JSON plan containing run_id and nodes")
    parser.add_argument("--manifest", type=Path, required=True, help="append-only JSONL manifest path")
    parser.add_argument("--accept-completed", action="store_true", help="use successful CLI exit as this run's explicit leaf check")
    args = parser.parse_args(argv)
    run_id, nodes, options = _load_plan(args.plan)
    accept = (lambda _node, result: result.status == "completed") if args.accept_completed else None
    print(json.dumps(run_tree(nodes, manifest_path=args.manifest, run_id=run_id, accept=accept, **options), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
