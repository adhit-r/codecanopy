# CodeCanopy runtime contract

This contract defines CodeCanopy's provider-neutral planning behavior and the small local runtime boundary for Codex and Claude CLIs. Providers and hosts enforce their own model availability, concurrency, sandbox policy, permissions, and approvals. The contract cannot expand user authority.

## Node record

The planning and normalized-result contracts record every node with its ID, parent, role, objective, deliverable, non-goals, baseline, read scope, write scope, produced artifacts, consumed artifacts, dependency IDs, acceptance check, evidence tier, normalized complexity score, normalized size score, weighted routing score, selected model tier, execution surface, provider, timeout, remaining budget, delegation permission, stop condition, and Git mode. The current local runtime implicitly uses `execution_surface: local_cli` and persists provider rather than the execution-surface field; do not infer app-task or future-adapter execution from its manifest. The baseline records one immutable commit plus any accepted dependency commits materialized into it. A child inherits only the parent authority and may narrow, never expand, its scope or budget.

Use an ownership tree for parent authority, scope, budget, questions, and integration. Use a separate artifact dependency DAG for scheduling. Only leaves with accepted dependencies may execute.

## Provider request, result, and isolation

Execution surface and provider are separate decisions. The implemented local CLI provider choice is per node: `codex` or `claude`. It is independent of the capability role and must be recorded before dispatch. A local request contains the prompt, preferred provider, timeout, working directory, explicit fallback consent, and read or write access. Arbitrary command overrides are not part of the request. The adapter first checks the selected CLI. Codex ignores user config and rules, disables project instructions and workspace network, prevents child-shell environment inheritance and login profiles, and runs with a never-escalate policy, explicit `read-only` or `workspace-write` sandbox, and ephemeral session. Claude runs in safe, non-persistent mode with a bounded file-tool allowlist; customizations, Bash, agents, browser, slash-command, web, and MCP tools are disabled. Read-only Claude nodes use `plan`; writing nodes use isolated-worktree `acceptEdits`. Turns are bounded, and the root runs acceptance checks. The adapter prepends the trust boundary and passes the result as one argument, never through a shell. Codex app tasks and future adapters follow separate contracts and are not represented as local `ProviderRequest` values.

The local result is `completed`, `failed`, `timed_out`, or `unavailable`, with the requested and actual provider, `fallback_used`, exit code, bounded output, and error. Fallback is denied by default. Catalog-backed CLI runs never translate a frozen Claude alias to Codex: an unavailable Claude provider blocks the node. The legacy direct provider API may use Codex only when the caller authorized that exact transition before dispatch and supplied no provider-specific model setting; the result records it. A run failure or timeout never triggers fallback. The provider receives only an allowlist of basic process variables and that provider's recognized authentication variables, not the parent environment.

Writing nodes use a fresh detached Git worktree below a caller-owned worktree root and the recorded immutable baseline. Every declared dependency requires an exact immutable commit mapping, and each mapped commit must already be an ancestor of the node baseline; missing and partial mappings fail before dispatch. The caller remains responsible for independently proving that a mapped commit is the accepted predecessor output. On an interrupted retry, reuse requires the expected Git repository, registered worktree root, and exact recorded baseline; a `.git` marker alone is insufficient. Reject absolute or escaping worktree names. The adapter does not merge or clean up a worktree, and a provider result does not bypass the normal integration barrier.

Append a proof receipt as owner-only, no-follow JSONL for every attempt. Receipts bind run, node, baseline, provider/result metadata, and SHA-256 hashes of the original prompt, secured dispatch prompt, and bounded output; they store no raw prompt or output. They are execution evidence only. A successful CLI exit, receipt, or local check is not proof of provider quality, staging, production, or task acceptance.

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

Route `routing_score <= worker_max_score` to `worker`, values up to `expert_max_score` to `expert`, and larger values to `lead`. Root, integration, or security-sensitive decisions always use `lead`; explicit review work uses `reviewer`; missing or uncertain signals use at least `expert`. If a frozen exact model is unavailable, block the node. A different exact model requires explicit user authorization for that transition and a new frozen execution contract.

The bundled selectors are `auto`. The local JSON plan must contain an explicit selected `model_tier` for every node; missing or invalid tier data blocks before discovery, manifest creation, or dispatch. At new-run start, after scoring selects that tier and before manifest creation, resolve each selected provider catalog exactly once. The manifest stores a bounded snapshot for each selected provider: provider, resolved role IDs or aliases and efforts, source, optional source version, and canonical hash. Each node receipt repeats only its matching provider snapshot and hash. Neither record stores raw provider catalog payloads, credentials, prompts, or outputs. The frozen catalog stays in effect through execution and resume; a later host default or lower-capability catalog entry applies only to a new run, never midway through a tree. A malformed, unsafe, incomplete, missing, or hash-mismatched snapshot blocks dispatch or resume. Codex receives exact IDs from authenticated structured host metadata. Claude receives provider aliases; record an exact backing ID only when the completed JSON output has unambiguous `modelUsage` evidence. Previews are not intentionally selected.

## Integration barriers and collisions

Before accepting a child, its parent verifies every required produced artifact, checks its baseline and assigned paths, runs the child acceptance check, then runs its own integration check. The parent emits one normalized result only after that barrier passes. The root alone accepts the integrated goal and declares completion.

Before dispatching a source-level leaf with accepted dependencies, the root reviews their commits and integrates them in artifact-DAG order into a fresh checkpoint. That immutable checkpoint becomes the leaf's recorded baseline, so its acceptance check runs against the predecessor code it consumes. Workers never construct or update integration baselines. A changed dependency invalidates affected descendants; the root creates a new checkpoint and redispatches them rather than rebasing an active worker.

One writer owns a path at a time. Shared files, lockfiles, generated schemas, and integration files return to the nearest common parent. Dirty overlap, baseline drift, scope crossing, or an unresolved merge conflict stops the affected lane; do not resolve it by assigning the shared file to another active child.

## Retry and subtree replan

Retry a failed node once only when new evidence justifies it. Repeated, semantic, or authorization failures return to the parent as `blocked` rather than spawning more work. When a contract, artifact, or acceptance condition changes, invalidate only descendants that depend on it; accepted unrelated nodes remain valid. Replan an affected subtree at most once, within remaining effective limits.

## Local manifests and recovery

`ManifestStore(path)` writes size-bounded, owner-only, no-follow JSONL events with monotonically increasing sequence numbers and validated lifecycle transitions. It stores a prompt hash, never a raw prompt. Recovery records interrupted nodes as `ready` or caller-selected `blocked`, never as successful. Accepted state is never reused across invocations; start a new run after reviewing it. Before redispatch, the parent verifies the recorded baseline, dependency acceptance, provider result, registered detached worktree, and evidence. A manifest remains local recovery evidence, not a cryptographically authenticated audit trail, secret store, distributed lock, or durable scheduler.

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
