# CodeCanopy runtime contract

This contract defines CodeCanopy's provider-neutral planning behavior and the small local runtime boundary for Codex and Claude CLIs. Providers and hosts enforce their own model availability, concurrency, sandbox policy, permissions, and approvals. The contract cannot expand user authority.

## Node record

Record every node with its ID, parent, role, objective, deliverable, non-goals, baseline, read scope, write scope, produced artifacts, consumed artifacts, dependency IDs, acceptance check, evidence tier, normalized complexity score, normalized size score, weighted routing score, selected model tier, provider, timeout, remaining budget, delegation permission, stop condition, and Git mode. The baseline records one immutable commit plus any accepted dependency commits materialized into it. A child inherits only the parent authority and may narrow, never expand, its scope or budget.

Use an ownership tree for parent authority, scope, budget, questions, and integration. Use a separate artifact dependency DAG for scheduling. Only leaves with accepted dependencies may execute.

## Provider request, result, and isolation

Provider choice is per node: `codex` or `claude`. It is independent of the capability role and must be recorded before dispatch. A local request contains the prompt, preferred provider, timeout, working directory, and optional command override. The adapter first checks the selected CLI. Its supported headless commands are `codex exec --skip-git-repo-check --json` and `claude --print --output-format json`; it passes the prompt as one argument, never through a shell.

The local result is `completed`, `failed`, `timed_out`, or `unavailable`, with the requested and actual provider, `fallback_used`, exit code, output, and error. A Claude request whose executable is unavailable may use Codex only if Codex is available; that is the sole fallback and the result must explicitly record it. A run failure or timeout never triggers fallback. No provider change is silent. Credentials are never copied, stored in the request/receipt, or passed from one provider to another; each CLI uses its own local authentication.

Writing nodes use a fresh detached Git worktree below a caller-owned worktree root and the recorded immutable baseline. Reject absolute or escaping worktree names. The adapter does not merge or clean up a worktree, and a provider result does not bypass the normal integration barrier.

Append a proof receipt as JSONL for every attempt. Receipts contain provider/result metadata plus SHA-256 hashes of the prompt and output, not their raw contents. They are execution evidence only; a successful CLI exit, receipt, or local check is not proof of provider quality, staging, production, or task acceptance.

## Lifecycle and readiness

`draft -> planned -> ready -> active -> returned -> accepted` is the successful path. A node may move to `blocked` when required evidence, authorization, a provider capability check, or a clean scope is unavailable. A timeout returns a `timed_out` provider result and remains unaccepted. A changed contract, failed prerequisite, changed baseline, missing receipt, or failed acceptance check moves affected descendants to `invalidated`; they return to `draft` only through an allowed subtree replan.

A planned leaf is ready when all consumed artifacts and dependency nodes are accepted, its immutable baseline contains the exact accepted source dependencies it will test against, its assigned paths do not overlap an active writer, its acceptance check is explicit, and its execution fits the remaining budget. Depth and total-node capacity gate creating children; active-child capacity gates dispatch, not readiness. Dispatch the deepest ready critical-path leaves first within the active-child limit.

## Automatic model routing

During planning, the root estimates two normalized node signals from observable evidence: `complexity_score` for decisions, security, cross-component dependencies, integration, external capability, and failure modes; and `size_score` for owned paths, artifacts, checks, and expected coordination surface. The planner does not ask the user to select a model.

With the configured weights, calculate:

```text
routing_score = (complexity_weight * complexity_score + size_weight * size_score)
                 / (complexity_weight + size_weight)
```

Route `routing_score <= worker_max_score` to `worker`, values up to `expert_max_score` to `expert`, and larger values to `lead`. Root, integration, or security-sensitive decisions always use `lead`; explicit review work uses `reviewer`; missing or uncertain signals use at least `expert`. If the selected model is unavailable, return the node to the lead or use a documented safe tier; never silently downgrade.

## Integration barriers and collisions

Before accepting a child, its parent verifies every required produced artifact, checks its baseline and assigned paths, runs the child acceptance check, then runs its own integration check. The parent emits one normalized result only after that barrier passes. The root alone accepts the integrated goal and declares completion.

Before dispatching a source-level leaf with accepted dependencies, the root reviews their commits and integrates them in artifact-DAG order into a fresh checkpoint. That immutable checkpoint becomes the leaf's recorded baseline, so its acceptance check runs against the predecessor code it consumes. Workers never construct or update integration baselines. A changed dependency invalidates affected descendants; the root creates a new checkpoint and redispatches them rather than rebasing an active worker.

One writer owns a path at a time. Shared files, lockfiles, generated schemas, and integration files return to the nearest common parent. Dirty overlap, baseline drift, scope crossing, or an unresolved merge conflict stops the affected lane; do not resolve it by assigning the shared file to another active child.

## Retry and subtree replan

Retry a failed node once only when new evidence justifies it. Repeated, semantic, or authorization failures return to the parent as `blocked` rather than spawning more work. When a contract, artifact, or acceptance condition changes, invalidate only descendants that depend on it; accepted unrelated nodes remain valid. Replan an affected subtree at most once, within remaining effective limits.

## Local manifests and recovery

`ManifestStore(path)` writes caller-selected JSONL append-only events with monotonically increasing sequence numbers. A run records its state; each node records its parent, dependencies, immutable baseline, state, checks, and invalidations. Recovery records interrupted nodes as `ready` or caller-selected `blocked`, never as successful. Before redispatch, the parent must verify that the recorded baseline, dependency acceptance, provider result, worktree, and evidence still match the current node contract. Otherwise invalidate only downstream ownership/dependency descendants, create a new immutable baseline where needed, and replan within the existing retry and subtree limits. A manifest is local recovery evidence, not a durable scheduler, secret store, distributed lock, or production audit trail.

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

Include the provider result and proof-receipt path in `evidence` when a local provider ran. `done` is not parent acceptance. The parent accepts only after its integration barrier passes. Local checks remain local evidence and never imply staging or production proof.
