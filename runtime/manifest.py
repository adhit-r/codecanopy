"""Append-only, restart-safe execution manifests for CodeCanopy."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

from .safeio import open_private, private_path

try:  # ``fcntl`` is stdlib on the Unix hosts CodeCanopy currently supports.
    import fcntl
except ImportError:  # pragma: no cover - retained for importability elsewhere.
    fcntl = None


NODE_STATES = frozenset({"draft", "planned", "ready", "active", "returned", "accepted", "blocked", "invalidated"})
RUN_STATES = frozenset({"planned", "active", "blocked", "completed"})
INVALIDATION_RULE = "parent-or-dependency-descendant"
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_MANIFEST_EVENTS = 20_000
MAX_EVENT_BYTES = 64 * 1024
INITIAL_NODE_STATES = frozenset({"draft", "planned", "ready"})
NODE_TRANSITIONS = {
    "draft": frozenset({"planned", "ready", "blocked", "invalidated"}),
    "planned": frozenset({"ready", "active", "blocked", "invalidated"}),
    "ready": frozenset({"active", "blocked", "invalidated"}),
    "active": frozenset({"ready", "returned", "blocked", "invalidated"}),
    "returned": frozenset({"ready", "accepted", "blocked", "invalidated"}),
    "accepted": frozenset({"invalidated"}),
    "blocked": frozenset({"ready", "invalidated"}),
    "invalidated": frozenset({"draft"}),
}
RUN_TRANSITIONS = {
    "planned": frozenset({"active", "blocked", "completed"}),
    "active": frozenset({"planned", "blocked", "completed"}),
    "blocked": frozenset({"planned", "active"}),
    "completed": frozenset({"active"}),
}


class ManifestError(ValueError):
    """Raised when a manifest cannot be safely reconstructed or extended."""


class ManifestStore:
    """A JSONL event log. Snapshots are reconstructed; existing rows are never rewritten."""

    def __init__(self, path: str | Path) -> None:
        self.path = private_path(path)

    def create_run(self, run_id: str, *, state: str = "planned", **details: Any) -> dict[str, Any]:
        self._require_run_state(state)
        if run_id in self._runs():
            raise ManifestError(f"run already exists: {run_id}")
        return self._append({"kind": "run-created", "run_id": run_id, "state": state, "details": details})

    def set_run_state(self, run_id: str, state: str) -> dict[str, Any]:
        current = self._require_run(run_id)
        self._require_run_state(state)
        self._require_transition(current["state"], state, RUN_TRANSITIONS, "run")
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
        if state not in INITIAL_NODE_STATES:
            raise ManifestError(f"node must start in one of: {', '.join(sorted(INITIAL_NODE_STATES))}")
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
        current = self._require_node(run_id, node_id)
        self._require_state(state)
        self._require_transition(current["state"], state, NODE_TRANSITIONS, "node")
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

    def _require_run(self, run_id: str) -> dict[str, Any]:
        runs = self._runs()
        if run_id not in runs:
            raise ManifestError(f"unknown run: {run_id}")
        return runs[run_id]

    def _require_node(self, run_id: str, node_id: str) -> dict[str, Any]:
        nodes = self.snapshot(run_id)["nodes"]
        if node_id not in nodes:
            raise ManifestError(f"unknown node: {node_id}")
        return nodes[node_id]

    @staticmethod
    def _require_state(state: str) -> None:
        if state not in NODE_STATES:
            raise ManifestError(f"unknown state: {state}")

    @staticmethod
    def _require_run_state(state: str) -> None:
        if state not in RUN_STATES:
            raise ManifestError(f"unknown run state: {state}")

    @staticmethod
    def _require_transition(current: str, state: str, transitions: Mapping[str, frozenset[str]], subject: str) -> None:
        if state == current:
            return
        if state not in transitions[current]:
            raise ManifestError(f"illegal {subject} transition: {current} -> {state}")

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
        try:
            handle = open_private(self.path, append=True)
        except ValueError as error:
            raise ManifestError(str(error)) from error
        with handle:
            self._lock(handle, exclusive=True)
            try:
                handle.seek(0)
                sequence = self._last_sequence(handle) + 1
                if sequence > MAX_MANIFEST_EVENTS:
                    raise ManifestError("manifest event limit exceeded")
                row = {"seq": sequence, **event}
                serialized = json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
                encoded_size = len(serialized.encode("utf-8"))
                if encoded_size > MAX_EVENT_BYTES:
                    raise ManifestError("manifest event size limit exceeded")
                if os.fstat(handle.fileno()).st_size + encoded_size > MAX_MANIFEST_BYTES:
                    raise ManifestError("manifest size limit exceeded")
                handle.seek(0, os.SEEK_END)
                handle.write(serialized)
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
                self._require_run_state(row.get("state"))
                if not isinstance(row.get("details"), Mapping):
                    raise ManifestError("invalid run-created details")
                runs[run_id] = {"run_id": run_id, "state": row["state"], "details": row["details"], "nodes": {}, "seq": row["seq"]}
                continue
            if run_id not in runs:
                raise ManifestError(f"event before run creation: {run_id}")
            run = runs[run_id]
            run["seq"] = row["seq"]
            if kind == "run-state":
                self._require_run_state(row.get("state"))
                self._require_transition(run["state"], row["state"], RUN_TRANSITIONS, "run")
                run["state"] = row["state"]
            elif kind == "node-recorded":
                node_id = row.get("node_id")
                if not isinstance(node_id, str):
                    raise ManifestError("invalid node id")
                if node_id in run["nodes"]:
                    raise ManifestError(f"duplicate node event: {node_id}")
                self._require_state(row.get("state"))
                if row["state"] not in INITIAL_NODE_STATES:
                    raise ManifestError("invalid initial node state")
                dependencies = row.get("dependencies")
                if not isinstance(dependencies, list) or not all(isinstance(item, str) for item in dependencies):
                    raise ManifestError(f"invalid dependencies for node: {node_id}")
                if set(dependencies) - set(run["nodes"]):
                    raise ManifestError(f"node {node_id} has unknown dependencies")
                if row.get("parent_id") is not None and row["parent_id"] not in run["nodes"]:
                    raise ManifestError(f"node {node_id} has an unknown parent")
                if not isinstance(row.get("details"), Mapping):
                    raise ManifestError(f"node {node_id} has invalid details")
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
                node = self._event_node(run, row)
                self._require_state(row.get("state"))
                self._require_transition(node["state"], row["state"], NODE_TRANSITIONS, "node")
                node["state"] = row["state"]
            elif kind == "check-recorded":
                node = self._event_node(run, row)
                if not isinstance(row.get("check"), Mapping):
                    raise ManifestError("invalid check event")
                node["checks"].append(row["check"])
            elif kind == "node-invalidated":
                node = self._event_node(run, row)
                source_node_id = row.get("source_node_id")
                reason = row.get("reason")
                rule = row.get("rule")
                if (
                    not isinstance(source_node_id, str)
                    or source_node_id not in run["nodes"]
                    or not isinstance(reason, str)
                    or not reason
                    or rule != INVALIDATION_RULE
                ):
                    raise ManifestError("invalid node-invalidated event")
                self._require_transition(node["state"], "invalidated", NODE_TRANSITIONS, "node")
                node["state"] = "invalidated"
                node["invalidations"].append(
                    {"source_node_id": source_node_id, "reason": reason, "rule": rule}
                )
            elif kind == "node-recovered":
                node = self._event_node(run, row)
                self._require_state(row.get("state"))
                self._require_transition(node["state"], row["state"], NODE_TRANSITIONS, "node")
                node["state"] = row["state"]
            else:
                raise ManifestError(f"unknown event kind: {kind}")
        return runs

    def _events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            handle = open_private(self.path, append=False)
        except ValueError as error:
            raise ManifestError(str(error)) from error
        with handle:
            self._lock(handle, exclusive=False)
            try:
                return list(self._validated_rows(handle))
            finally:
                self._unlock(handle)

    @classmethod
    def _last_sequence(cls, handle: Any) -> int:
        return max((row["seq"] for row in cls._validated_rows(handle)), default=0)

    @staticmethod
    def _event_node(run: Mapping[str, Any], row: Mapping[str, Any]) -> dict[str, Any]:
        node_id = row.get("node_id")
        if not isinstance(node_id, str) or node_id not in run["nodes"]:
            raise ManifestError(f"event references unknown node: {node_id}")
        return run["nodes"][node_id]

    @staticmethod
    def _validated_rows(handle: Any) -> Iterable[dict[str, Any]]:
        if os.fstat(handle.fileno()).st_size > MAX_MANIFEST_BYTES:
            raise ManifestError("manifest size limit exceeded")
        previous = 0
        events = 0
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            events += 1
            if events > MAX_MANIFEST_EVENTS:
                raise ManifestError("manifest event limit exceeded")
            if len(line.encode("utf-8")) > MAX_EVENT_BYTES:
                raise ManifestError("manifest event size limit exceeded")
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ManifestError(f"invalid JSONL at line {line_number}") from exc
            if not isinstance(row, dict) or row.get("seq") != previous + 1:
                raise ManifestError(f"non-deterministic sequence at line {line_number}")
            previous = row["seq"]
            yield row

    @staticmethod
    def _lock(handle: Any, *, exclusive: bool) -> None:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)

    @staticmethod
    def _unlock(handle: Any) -> None:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
