"""Append-only, restart-safe execution manifests for CodeCanopy."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

try:  # ``fcntl`` is stdlib on the Unix hosts CodeCanopy currently supports.
    import fcntl
except ImportError:  # pragma: no cover - retained for importability elsewhere.
    fcntl = None


NODE_STATES = frozenset({"draft", "planned", "ready", "active", "returned", "accepted", "blocked", "invalidated"})
RUN_STATES = frozenset({"planned", "active", "blocked", "completed"})
INVALIDATION_RULE = "parent-or-dependency-descendant"


class ManifestError(ValueError):
    """Raised when a manifest cannot be safely reconstructed or extended."""


class ManifestStore:
    """A JSONL event log. Snapshots are reconstructed; existing rows are never rewritten."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def create_run(self, run_id: str, *, state: str = "planned", **details: Any) -> dict[str, Any]:
        self._require_run_state(state)
        if run_id in self._runs():
            raise ManifestError(f"run already exists: {run_id}")
        return self._append({"kind": "run-created", "run_id": run_id, "state": state, "details": details})

    def set_run_state(self, run_id: str, state: str) -> dict[str, Any]:
        self._require_run(run_id)
        self._require_run_state(state)
        return self._append({"kind": "run-state", "run_id": run_id, "state": state})

    def status(self, run_id: str) -> dict[str, Any]:
        """Return a compact, human-readable run summary and critical frontier."""
        snapshot = self.snapshot(run_id)
        nodes = snapshot["nodes"]
        counts: dict[str, int] = {}
        frontier: list[str] = []
        for node_id, node in nodes.items():
            state = node["state"]
            counts[state] = counts.get(state, 0) + 1
            if state == "ready" and all(nodes[dependency]["state"] == "accepted" for dependency in node["dependencies"]):
                frontier.append(node_id)
        return {
            "run_id": run_id,
            "state": snapshot["state"],
            "node_counts": dict(sorted(counts.items())),
            "critical_frontier": sorted(frontier),
            "nodes": {
                node_id: {
                    "state": node["state"],
                    "dependencies": list(node["dependencies"]),
                    "checks": len(node["checks"]),
                }
                for node_id, node in sorted(nodes.items())
            },
        }

    def inspect_node(self, run_id: str, node_id: str) -> dict[str, Any]:
        """Return one node's recorded contract, checks, and invalidations."""
        snapshot = self.snapshot(run_id)
        try:
            return copy.deepcopy(snapshot["nodes"][node_id])
        except KeyError as exc:
            raise ManifestError(f"unknown node: {node_id}") from exc

    def record_node(
        self,
        run_id: str,
        node_id: str,
        *,
        parent_id: str | None = None,
        state: str = "draft",
        dependencies: Iterable[str] = (),
        baseline: Mapping[str, Any] | None = None,
        dependency_commits: Mapping[str, str] | None = None,
        **details: Any,
    ) -> dict[str, Any]:
        snapshot = self.snapshot(run_id)
        if node_id in snapshot["nodes"]:
            raise ManifestError(f"node already exists: {node_id}")
        if parent_id is not None and parent_id not in snapshot["nodes"]:
            raise ManifestError(f"unknown parent node: {parent_id}")
        self._require_state(state)
        dependency_ids = list(dependencies)
        unknown = set(dependency_ids) - set(snapshot["nodes"])
        if unknown:
            raise ManifestError(f"unknown dependency nodes: {', '.join(sorted(unknown))}")
        return self._append(
            {
                "kind": "node-recorded",
                "run_id": run_id,
                "node_id": node_id,
                "parent_id": parent_id,
                "state": state,
                "dependencies": dependency_ids,
                # Baselines are part of this first, immutable node record.
                "baseline": self._baseline(baseline, dependency_commits),
                "details": details,
            }
        )

    def set_node_state(self, run_id: str, node_id: str, state: str) -> dict[str, Any]:
        self._require_node(run_id, node_id)
        self._require_state(state)
        return self._append({"kind": "node-state", "run_id": run_id, "node_id": node_id, "state": state})

    def record_check(
        self,
        run_id: str,
        node_id: str,
        command: str,
        result: str,
        *,
        evidence: str | None = None,
    ) -> dict[str, Any]:
        self._require_node(run_id, node_id)
        return self._append(
            {
                "kind": "check-recorded",
                "run_id": run_id,
                "node_id": node_id,
                "check": {"command": command, "result": result, "evidence": evidence},
            }
        )

    def invalidate_descendants(self, run_id: str, source_node_id: str, reason: str) -> list[str]:
        """Invalidate only nodes downstream through ownership or declared dependencies."""
        snapshot = self.snapshot(run_id)
        if source_node_id not in snapshot["nodes"]:
            raise ManifestError(f"unknown node: {source_node_id}")
        affected: list[str] = []
        frontier = [source_node_id]
        seen = {source_node_id}
        while frontier:
            source = frontier.pop(0)
            for node_id, node in snapshot["nodes"].items():
                if node_id in seen:
                    continue
                if node["parent_id"] == source or source in node["dependencies"]:
                    seen.add(node_id)
                    frontier.append(node_id)
                    if node["state"] != "invalidated":
                        affected.append(node_id)
        for node_id in affected:
            self._append(
                {
                    "kind": "node-invalidated",
                    "run_id": run_id,
                    "node_id": node_id,
                    "source_node_id": source_node_id,
                    "reason": reason,
                    "rule": INVALIDATION_RULE,
                }
            )
        return affected

    def recover_interrupted(self, run_id: str, *, blocked: Iterable[str] = ()) -> list[str]:
        """Return interrupted active nodes to an explicit non-executing state."""
        snapshot = self.snapshot(run_id)
        blocked_ids = set(blocked)
        unknown = blocked_ids - set(snapshot["nodes"])
        if unknown:
            raise ManifestError(f"unknown blocked nodes: {', '.join(sorted(unknown))}")
        recovered: list[str] = []
        for node_id, node in snapshot["nodes"].items():
            if node["state"] != "active":
                continue
            state = "blocked" if node_id in blocked_ids else "ready"
            self._append(
                {
                    "kind": "node-recovered",
                    "run_id": run_id,
                    "node_id": node_id,
                    "state": state,
                    "reason": "interrupted execution was not completed",
                }
            )
            recovered.append(node_id)
        return recovered

    def snapshot(self, run_id: str) -> dict[str, Any]:
        runs = self._runs()
        try:
            return copy.deepcopy(runs[run_id])
        except KeyError as exc:
            raise ManifestError(f"unknown run: {run_id}") from exc

    def _require_run(self, run_id: str) -> None:
        if run_id not in self._runs():
            raise ManifestError(f"unknown run: {run_id}")

    def _require_node(self, run_id: str, node_id: str) -> None:
        if node_id not in self.snapshot(run_id)["nodes"]:
            raise ManifestError(f"unknown node: {node_id}")

    @staticmethod
    def _require_state(state: str) -> None:
        if state not in NODE_STATES:
            raise ManifestError(f"unknown state: {state}")

    @staticmethod
    def _require_run_state(state: str) -> None:
        if state not in RUN_STATES:
            raise ManifestError(f"unknown run state: {state}")

    @staticmethod
    def _baseline(
        baseline: Mapping[str, Any] | None, dependency_commits: Mapping[str, str] | None
    ) -> dict[str, Any] | None:
        if baseline is not None and dependency_commits is not None:
            raise ManifestError("pass dependency commits inside baseline or separately, not both")
        if baseline is None:
            return None if dependency_commits is None else {"commit": None, "dependency_commits": dict(sorted(dependency_commits.items()))}
        value = dict(baseline)
        commits = value.get("dependency_commits", {})
        if not isinstance(commits, Mapping):
            raise ManifestError("baseline dependency_commits must be a mapping")
        value["dependency_commits"] = dict(sorted(commits.items()))
        if "commit" not in value:
            raise ManifestError("baseline requires immutable commit")
        return value

    def _append(self, event: dict[str, Any]) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a+", encoding="utf-8") as handle:
            self._lock(handle, exclusive=True)
            try:
                handle.seek(0)
                sequence = self._last_sequence(handle) + 1
                row = {"seq": sequence, **event}
                handle.seek(0, os.SEEK_END)
                handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
                return row
            finally:
                self._unlock(handle)

    def _runs(self) -> dict[str, dict[str, Any]]:
        runs: dict[str, dict[str, Any]] = {}
        for row in self._events():
            run_id = row.get("run_id")
            kind = row.get("kind")
            if kind == "run-created":
                if not isinstance(run_id, str) or run_id in runs:
                    raise ManifestError("invalid or duplicate run-created event")
                runs[run_id] = {"run_id": run_id, "state": row["state"], "details": row["details"], "nodes": {}, "seq": row["seq"]}
                continue
            if run_id not in runs:
                raise ManifestError(f"event before run creation: {run_id}")
            run = runs[run_id]
            run["seq"] = row["seq"]
            if kind == "run-state":
                run["state"] = row["state"]
            elif kind == "node-recorded":
                node_id = row["node_id"]
                if node_id in run["nodes"]:
                    raise ManifestError(f"duplicate node event: {node_id}")
                run["nodes"][node_id] = {
                    "node_id": node_id,
                    "parent_id": row["parent_id"],
                    "state": row["state"],
                    "dependencies": row["dependencies"],
                    "baseline": row["baseline"],
                    "details": row["details"],
                    "checks": [],
                    "invalidations": [],
                }
            elif kind == "node-state":
                run["nodes"][row["node_id"]]["state"] = row["state"]
            elif kind == "check-recorded":
                run["nodes"][row["node_id"]]["checks"].append(row["check"])
            elif kind == "node-invalidated":
                node = run["nodes"][row["node_id"]]
                node["state"] = "invalidated"
                node["invalidations"].append({key: row[key] for key in ("source_node_id", "reason", "rule")})
            elif kind == "node-recovered":
                run["nodes"][row["node_id"]]["state"] = row["state"]
            else:
                raise ManifestError(f"unknown event kind: {kind}")
        return runs

    def _events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as handle:
            self._lock(handle, exclusive=False)
            try:
                rows: list[dict[str, Any]] = []
                previous = 0
                for line_number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ManifestError(f"invalid JSONL at line {line_number}") from exc
                    if not isinstance(row, dict) or row.get("seq") != previous + 1:
                        raise ManifestError(f"non-deterministic sequence at line {line_number}")
                    previous = row["seq"]
                    rows.append(row)
                return rows
            finally:
                self._unlock(handle)

    @staticmethod
    def _last_sequence(handle: Any) -> int:
        previous = 0
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ManifestError(f"invalid JSONL at line {line_number}") from exc
            if not isinstance(row, dict) or row.get("seq") != previous + 1:
                raise ManifestError(f"non-deterministic sequence at line {line_number}")
            previous = row["seq"]
        return previous

    @staticmethod
    def _lock(handle: Any, *, exclusive: bool) -> None:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)

    @staticmethod
    def _unlock(handle: Any) -> None:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
