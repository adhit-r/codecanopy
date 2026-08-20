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
- Depth, concurrency, and token budget. Reserve at least 30% for root integration and verification.

Use a platform goal tracker only when the user explicitly requests a tracked goal.

## Present the canopy plan

Before dispatch, show a compact ownership tree. Every node states its role, outcome, owned paths or read-only scope, dependencies, check, and budget:

```text
G root: <goal>
├─ S1 SME/read: <decision> | check <evidence>
├─ W1 worker/write: <outcome> | owns <paths> | check <command>
└─ R1 reviewer/read: <verdict> | after W1
```

Dependencies may form a DAG; ownership remains a tree. Proceed after presenting the plan when requested local work is authorized. Ask before scope expansion, destructive actions, credentials, production changes, or remote writes.

Default limits: depth 2, three children per parent, four concurrent agents, eight total child tasks, and two waves. Lower them for smaller work. Increase them only for named independent outcomes while preserving the integration reserve.

A node must have an independently verifiable outcome and add parallel speed or independent judgment. Requested headcount is not work. Never create agents to meet a number, restate context, or write the final report.

## Route roles

- **Root lead:** approves decomposition, owns shared files and integration, verifies, and closes.
- **SME:** handles architecture, contracts, security, or plan/diff review; normally read-only. Every multi-writer canopy gets one independent reviewer.
- **Worker:** handles one bounded search, test, mechanical edit, or narrow root-cause fix with the smallest capable model. Prefer a chore/worker role when supported.
- **Child worker:** requires explicit delegation permission, remaining depth, disjoint scope, and its own check. It never delegates again.

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
