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

from .manifest import ManifestError, ManifestStore, UnknownRunError
from .model_catalog import ResolvedCatalog, load_role_settings, resolve_model_catalog
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
    validate_model_catalog_snapshot,
    validate_provider_settings,
)


_NODE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_RUN_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_IMMUTABLE_COMMIT = re.compile(r"^[0-9a-fA-F]{40,64}$")
_POLICY_HASH = re.compile(r"^[0-9a-f]{64}$")
_MODEL_TIERS = ("lead", "expert", "reviewer", "worker")
_BUNDLED_CONFIG = Path(__file__).resolve().parents[1] / "plugins/code-canopy/skills/code-canopy/assets/codecanopy.toml"
MAX_PLAN_BYTES = 1024 * 1024
MAX_NODES = 9
MAX_DEPTH = 3
MAX_DEPENDENCIES = 3

ExecutionSettings = Callable[["TreeNode"], tuple[str | None, str | None]]


class ReceiptEvidenceError(RuntimeError):
    """The provider returned, but its proof receipt could not be persisted."""


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
    model_tier: str | None = None

    def __post_init__(self) -> None:
        if not self.node_id or len(self.node_id) > 64 or not _NODE_ID.fullmatch(self.node_id):
            raise ValueError("node_id must contain 1-64 letters, numbers, '.', '_' or '-'")
        if not self.prompt.strip() or len(self.prompt) > MAX_PROMPT_CHARS:
            raise ValueError(f"prompt must contain 1-{MAX_PROMPT_CHARS} characters")
        if self.provider not in ("codex", "claude"):
            raise ValueError(f"unsupported provider: {self.provider}")
        if self.model_tier not in _MODEL_TIERS:
            raise ValueError(f"model_tier must be one of {list(_MODEL_TIERS)}")
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
        if "model_tier" not in value:
            raise ValueError("model_tier is required")
        model_tier = value["model_tier"]
        if not isinstance(node_id, str) or not isinstance(prompt, str):
            raise ValueError("node id and prompt must be strings")
        if not isinstance(provider, str) or not isinstance(baseline, str):
            raise ValueError("provider and baseline must be strings")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise ValueError("timeout_seconds must be a number")
        if worktree_name is not None and not isinstance(worktree_name, str):
            raise ValueError("worktree_name must be a string")
        if not isinstance(model_tier, str):
            raise ValueError("model_tier must be a string")
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
            model_tier=model_tier,
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
    execution_settings: ExecutionSettings | None = None,
    execution_policy_hash: str | None = None,
    model_catalog_hash: str | None = None,
    provider_catalogs: Mapping[ProviderName, ResolvedCatalog] | None = None,
    require_provider_catalogs: bool = False,
) -> dict[str, object]:
    """Run ready nodes in dependency order and leave resume evidence in JSONL."""
    ordered = _topological(tuple(nodes))
    _validate_run_id(run_id)
    if execution_policy_hash is not None and not _POLICY_HASH.fullmatch(execution_policy_hash):
        raise ValueError("execution_policy_hash must be a lowercase SHA-256 digest")
    if model_catalog_hash is not None and not _POLICY_HASH.fullmatch(model_catalog_hash):
        raise ValueError("model_catalog_hash must be a lowercase SHA-256 digest")
    provider_names = {node.provider for node in ordered}
    supplied_catalogs = _serialize_provider_catalogs(provider_catalogs, provider_names) if provider_catalogs is not None else None
    if supplied_catalogs is not None and model_catalog_hash is not None:
        raise ValueError("model_catalog_hash cannot be combined with provider catalog snapshots")
    settings_by_node = (
        _resolve_execution_settings(ordered, supplied_catalogs, execution_settings)
        if supplied_catalogs is not None or not require_provider_catalogs
        else {}
    )
    if worktree_root is not None and repo is None:
        raise ValueError("repo is required when worktree_root is provided")
    store = ManifestStore(manifest_path)
    try:
        snapshot = store.snapshot(run_id)
    except UnknownRunError:
        if require_provider_catalogs and supplied_catalogs is None:
            raise ManifestError("provider catalog snapshots are required before manifest creation")
        store.create_run(
            run_id,
            state="planned",
            repo=str(repo) if repo else None,
            model_catalog_hash=model_catalog_hash,
            provider_catalogs=supplied_catalogs,
        )
        snapshot = store.snapshot(run_id)
    else:
        if snapshot["details"].get("model_catalog_hash") != model_catalog_hash:
            raise ManifestError("saved model catalog does not match the requested catalog")
    stored_catalogs = _load_provider_catalogs(snapshot["details"].get("provider_catalogs"), provider_names)
    if supplied_catalogs is not None and stored_catalogs is not None and supplied_catalogs != stored_catalogs:
        raise ManifestError("saved provider catalog snapshots do not match the requested catalogs")
    catalogs = stored_catalogs if stored_catalogs is not None else supplied_catalogs
    if require_provider_catalogs and catalogs is None:
        raise ManifestError("saved run lacks provider catalog snapshots; start a new run with the current contract")
    if catalogs is not None and not settings_by_node:
        settings_by_node = _resolve_execution_settings(ordered, catalogs, execution_settings)
    if any(node["state"] == "accepted" for node in snapshot["nodes"].values()):
        raise ManifestError("accepted manifest state cannot be resumed; start a new run after reviewing evidence")

    recovered = store.recover_interrupted(run_id)
    if snapshot["state"] == "active":
        store.set_run_state(run_id, "planned")
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
        requested_model, requested_reasoning_effort = settings_by_node[node.node_id]
        if node.node_id in known:
            _verify_saved_contract(
                snapshot["nodes"][node.node_id],
                node,
                baseline,
                requested_model,
                requested_reasoning_effort,
                execution_policy_hash,
                catalogs[node.provider]["catalog_hash"] if catalogs is not None else model_catalog_hash,
            )
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
            model_tier=node.model_tier,
            requested_model=requested_model,
            requested_reasoning_effort=requested_reasoning_effort,
            execution_policy_hash=execution_policy_hash,
            model_catalog_hash=catalogs[node.provider]["catalog_hash"] if catalogs is not None else model_catalog_hash,
        )
    store.set_run_state(run_id, "active")
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
            model=settings_by_node[node.node_id][0],
            reasoning_effort=settings_by_node[node.node_id][1],
            model_catalog_hash=catalogs[node.provider]["catalog_hash"] if catalogs is not None else model_catalog_hash,
            model_catalog_snapshot=catalogs[node.provider] if catalogs is not None else None,
        )
        result = execute(request)
        receipt_path = receipts / f"{node.node_id}.jsonl"
        try:
            append_proof_receipt(
                receipt_path,
                request,
                result,
                run_id=run_id,
                node_id=node.node_id,
                baseline=resolved_baselines[node.node_id],
            )
        except (OSError, ValueError) as error:
            raise ReceiptEvidenceError(
                f"proof receipt evidence failed for node {node.node_id}"
            ) from error
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


def _serialize_provider_catalogs(
    catalogs: Mapping[ProviderName, ResolvedCatalog], provider_names: set[ProviderName]
) -> dict[str, dict[str, object]]:
    if set(catalogs) != provider_names:
        raise ValueError("provider catalog snapshots must exactly cover the planned providers")
    snapshots: dict[str, dict[str, object]] = {}
    for provider in sorted(provider_names):
        catalog = catalogs[provider]
        if not isinstance(catalog, ResolvedCatalog) or catalog.provider != provider:
            raise ValueError("provider catalog snapshots are invalid")
        roles = {
            tier: {"model": catalog.roles[tier].model, "reasoning_effort": catalog.roles[tier].reasoning_effort}
            for tier in _MODEL_TIERS
        }
        snapshots[provider] = validate_model_catalog_snapshot(
            {
                "provider": catalog.provider,
                "source": catalog.source,
                "source_version": catalog.source_version,
                "roles": roles,
                "catalog_hash": catalog.catalog_hash,
            },
            provider,
        )
    return snapshots


def _load_provider_catalogs(value: object, provider_names: set[ProviderName]) -> dict[str, dict[str, object]] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != provider_names:
        raise ManifestError("saved provider catalog snapshot is missing or invalid")
    try:
        return {
            provider: validate_model_catalog_snapshot(value[provider], provider)
            for provider in sorted(provider_names)
        }
    except ValueError as error:
        raise ManifestError("saved provider catalog snapshot is missing or invalid") from error


def _resolve_execution_settings(
    nodes: Sequence[TreeNode],
    catalogs: Mapping[str, Mapping[str, object]] | None,
    execution_settings: ExecutionSettings | None,
) -> dict[str, tuple[str | None, str | None]]:
    resolved: dict[str, tuple[str | None, str | None]] = {}
    for node in nodes:
        if catalogs is not None:
            roles = catalogs[node.provider].get("roles")
            setting = roles.get(node.model_tier) if isinstance(roles, Mapping) else None
            if not isinstance(setting, Mapping):
                raise ManifestError("saved provider catalog snapshot is invalid")
            settings = (setting.get("model"), setting.get("reasoning_effort"))
            if execution_settings is not None and execution_settings(node) != settings:
                raise ValueError("execution_settings must match the frozen provider catalog snapshot")
        else:
            settings = execution_settings(node) if execution_settings is not None else (None, None)
        if not isinstance(settings, tuple) or len(settings) != 2:
            raise ValueError("execution_settings must return an exact 2-tuple")
        model, reasoning_effort = settings
        validate_provider_settings(node.provider, model, reasoning_effort)
        resolved[node.node_id] = (model, reasoning_effort)
    return resolved


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


def _verify_saved_contract(
    current: Mapping[str, object],
    node: TreeNode,
    baseline: str,
    requested_model: str | None,
    requested_reasoning_effort: str | None,
    execution_policy_hash: str | None,
    model_catalog_hash: str | None,
) -> None:
    """Reject a same-ID redispatch when its recorded execution contract changed."""
    details = current.get("details", {})
    if not isinstance(details, Mapping):
        raise ManifestError(f"node {node.node_id} has an invalid saved contract")
    expected = {
        "prompt_hash": _prompt_hash(node.prompt),
        "provider": node.provider,
        "timeout_seconds": node.timeout_seconds,
        "worktree_name": node.worktree_name,
        "model_tier": node.model_tier,
        "requested_model": requested_model,
        "requested_reasoning_effort": requested_reasoning_effort,
        "execution_policy_hash": execution_policy_hash,
        "model_catalog_hash": model_catalog_hash,
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
    parser.add_argument("--config", type=Path, default=_BUNDLED_CONFIG, help="trusted CodeCanopy TOML used only for a new run")
    parser.add_argument("--worktree-root", type=Path, help="trusted isolated-worktree root")
    parser.add_argument("--receipt-dir", type=Path, help="trusted private receipt directory")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--status", action="store_true", help="show run state and dependency-ready frontier")
    action.add_argument("--inspect", metavar="NODE_ID", help="show one recorded node contract and evidence")
    parser.add_argument("--accept-completed", action="store_true", help="use successful CLI exit as this run's explicit leaf check")
    parser.add_argument("--allow-provider-fallback", action="store_true", help="legacy direct API only; catalog-backed CLI runs fail closed")
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
    if args.allow_provider_fallback:
        parser.error("--allow-provider-fallback is not supported for catalog-backed CLI runs")
    run_id, nodes = _load_plan(args.plan)
    store = ManifestStore(args.manifest)
    try:
        store.snapshot(run_id)
    except UnknownRunError:
        settings = load_role_settings(args.config)
        provider_catalogs = {
            provider: resolve_model_catalog(provider, settings)
            for provider in sorted({node.provider for node in nodes})
        }
    else:
        provider_catalogs = None
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
                provider_catalogs=provider_catalogs,
                require_provider_catalogs=True,
                execute=execute_provider,
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
