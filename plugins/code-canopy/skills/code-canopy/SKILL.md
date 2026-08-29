---
name: code-canopy
description: Use when an engineering requirement has independent implementation, investigation, or validation lanes and the user wants delegated team or swarm execution.
---

# CodeCanopy

Build the smallest useful agent tree. The root owns the goal, budget, integration state, and final verdict. Delegation never expands the user's scope or permissions.

## Ponytail gate

Understand the affected flow and callers first. Then stop at the first option that works: skip speculative work; reuse repository code; prefer standard-library, native-platform, or installed capabilities; otherwise make the minimum root-cause change. If one agent can finish safely, do not create a canopy.

Use `ponytail` when available. The gate above is the self-contained fallback.

## Establish the contract

Record:

- One end goal, non-goals, and observable acceptance checks.
- Evidence tier: static, unit, integration, staging, or production.
- Repository, branch, baseline commit, dirty files, and existing worktrees.
- Git mode: `read-only`, `edit`, `local-commit`, or `remote`. In `edit`, only the root writes; parallel writers require commit mode. Infer no more authority than the request grants.
- Node contract: ID, parent, role, objective, deliverable, non-goals, immutable baseline commit plus materialized dependency commits, read and write scope, produced and consumed artifacts, dependencies, acceptance check, evidence tier, normalized complexity and size scores, routing score, selected model tier, provider, timeout, remaining budget, delegation permission, stop condition, and Git mode.
- Effective limits, provider choice, timeout, and model preferences. Start with the bundled [defaults](assets/codecanopy.toml); host/admin policy and an explicit current user instruction take precedence over an optional project-root `.codecanopy.toml`, which takes precedence over built-in defaults. Unknown or invalid project values are ignored with a visible warning.

Use a platform goal tracker only when the user explicitly requests a tracked goal.

## Present the canopy plan

Before dispatch, show a compact ownership tree. Every node states its role, outcome, owned paths or read-only scope, dependencies, check, and budget:

```text
G root: <goal>
├─ S1 SME/read: <decision> | check <evidence>
├─ W1 worker/write: <outcome> | owns <paths> | check <command>
└─ R1 reviewer/read: <verdict> | after W1
```

The ownership tree records parent authority, scope, budget, questions, and integration. The artifact dependency DAG records readiness and execution order. Proceed after presenting the plan when requested local work is authorized. Ask before scope expansion, destructive actions, credentials, production changes, or remote writes.

Default limits: root depth `0`; maximum depth `3`; three children per node; nine total nodes including root; three active children; one subtree replan; a 35% root integration reserve; and one retry only with new evidence. Effective parallelism is the lower of the CodeCanopy configuration and host limit. Configuration only tunes planning limits and model preferences; it cannot grant Git, network, destructive, credential, production, or publication authority.

## Operate the recursive canopy

1. Establish the node contract, inspect scoped evidence and callers, then identify a candidate split.
2. Apply the Leaf Test: a node is atomic when it has one bounded deliverable and owner, one explicit acceptance check, coherent read or write scope, no unresolved user, product, or security decision, no dependency on a sibling's unfinished output, and fits its remaining model and planning limits.
3. For every planned node, estimate normalized `complexity_score` and `size_score` from observable scope, decisions, dependencies, artifacts, and checks. Compute the configured weighted routing score and select the smallest capable model tier automatically; do not ask the user to choose a model during planning. Root, integration, and security decisions route to `lead`; review work routes to `reviewer`; missing or uncertain scores route to at least `expert`.
4. For a non-atomic node, split only into independently usable outcome contracts. Delegate only when delegation is explicitly allowed and there is remaining depth, remaining total-node capacity, disjoint scope, explicit acceptance, and useful parallel or specialist value. Collapse the split when coordination costs more than that value.
5. Record the ownership tree and artifact DAG. Reserve parent integration capacity. Before dispatching a source-level leaf with accepted dependencies, the root integrates those commits in DAG order into a fresh immutable baseline and records it in the node packet. Then dispatch the deepest dependency-ready critical-path leaves within effective limits.
6. Before a local provider run, record the node's provider and timeout, check that its CLI is available, create its isolated worktree when it writes, and retain the provider result and proof receipt. A Claude request may fall back to Codex only when Claude is unavailable; the result and receipt must flag that fallback. Never share credentials or silently change providers.
7. Accept results bottom-up: a parent verifies required child artifacts, runs its own integration check, and emits one normalized result upward.
8. On changed contracts or failed dependent evidence, replan only the affected subtree. Stop only when root acceptance passes.

Use the [runtime contract](references/runtime-contract.md) for states, provider results, receipts, resume/invalidation, collision, retry, and normalized results. Use the [Codex adapter](references/codex-adapter.md) and [Claude adapter](references/claude-adapter.md) for current provider boundaries.

Requested headcount is not work. Never create agents to meet a number, restate context, or write the final report.

## Route roles

- **Root lead:** approves decomposition, owns shared files and integration, verifies, and closes.
- **SME:** handles architecture, contracts, security, or plan/diff review; normally read-only. Every multi-writer canopy gets one independent reviewer.
- **Worker:** handles one bounded search, test, mechanical edit, or narrow root-cause fix with the smallest capable model. Prefer a chore/worker role when supported.
- **Delegation-enabled child:** may recursively plan only within its inherited authority and only when the recursive conditions above hold. Its child scope must remain disjoint and independently accepted.

Use strong reasoning only for cross-component decisions, security, integration, or contradictory evidence. Give independent agents `fork_turns: none` and a narrow packet; use a small recent fork when needed and full history only when essential.

Before any agent writes or commits, read [execution-protocol.md](references/execution-protocol.md). Plan-only requests stop here.

## Verify and close

The root runs acceptance checks on the integrated state and labels evidence by tier. Failed checks return only to the responsible node. Local tests are not staging or production proof.

Complete only when the integrated state meets the acceptance checks. Report accepted commits or diffs, checks, skipped scope, and remaining risk. If evidence is incomplete, say `incomplete`; polish never upgrades the verdict.

## Pressure responses

| Pressure | Response |
|---|---|
| "Use N agents" | Derive nodes from independent outcomes. |
| "Everyone needs the transcript" | Send narrow packets and evidence pointers. |
| "Spend the whole budget" | Protect the root integration reserve. |
| "Add a reporting agent" | The root reports from accepted evidence. |
| "Push what passes unit tests" | Respect Git mode and evidence tier. |
