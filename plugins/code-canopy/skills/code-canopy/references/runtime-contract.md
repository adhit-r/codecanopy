# CodeCanopy runtime contract

This contract defines CodeCanopy's required planning behavior. Codex and its host environment enforce documented model availability, concurrency, sandbox policy, permissions, and approvals. CodeCanopy and the root explicitly create and verify worktree isolation where it is needed. The contract cannot expand user authority.

## Node record

Record every node with its ID, parent, role, objective, deliverable, non-goals, baseline, read scope, write scope, produced artifacts, consumed artifacts, dependency IDs, acceptance check, evidence tier, model tier, remaining budget, delegation permission, stop condition, and Git mode. A child inherits only the parent authority and may narrow, never expand, its scope or budget.

Use an ownership tree for parent authority, scope, budget, questions, and integration. Use a separate artifact dependency DAG for scheduling. Only leaves with accepted dependencies may execute.

## Lifecycle and readiness

`draft -> planned -> ready -> active -> returned -> accepted` is the successful path. A node may move to `blocked` when required evidence, authorization, or a clean scope is unavailable. A changed contract or failed prerequisite moves affected descendants to `invalidated`; they return to `draft` only through an allowed subtree replan.

A planned leaf is ready when all consumed artifacts and dependency nodes are accepted, its baseline remains valid, its assigned paths do not overlap an active writer, its acceptance check is explicit, and its execution fits the remaining budget. Depth and total-node capacity gate creating children; active-child capacity gates dispatch, not readiness. Dispatch the deepest ready critical-path leaves first within the active-child limit.

## Integration barriers and collisions

Before accepting a child, its parent verifies every required produced artifact, checks its baseline and assigned paths, runs the child acceptance check, then runs its own integration check. The parent emits one normalized result only after that barrier passes. The root alone accepts the integrated goal and declares completion.

One writer owns a path at a time. Shared files, lockfiles, generated schemas, and integration files return to the nearest common parent. Dirty overlap, baseline drift, scope crossing, or an unresolved merge conflict stops the affected lane; do not resolve it by assigning the shared file to another active child.

## Retry and subtree replan

Retry a failed node once only when new evidence justifies it. Repeated, semantic, or authorization failures return to the parent as `blocked` rather than spawning more work. When a contract, artifact, or acceptance condition changes, invalidate only descendants that depend on it; accepted unrelated nodes remain valid. Replan an affected subtree at most once, within remaining effective limits.

## Normalized result

Every completed or blocked node returns:

```text
status: done | blocked | no-change
result: <one sentence>
files: <paths or none>
commit: <sha or none>
checks: <command and result>
evidence: <path:line or artifact>
blocker: <exact obstacle or none>
```

`done` is not parent acceptance. The parent accepts only after its integration barrier passes. Local checks remain local evidence and never imply staging or production proof.
