# Recursive Canopy v0.2 Specification

## Goal

Replace CodeCanopy's fixed depth-two fan-out with a bounded recursive orchestration contract that finds the smallest verified path from an engineering requirement to accepted completion.

## Product promise

The smallest verified tree that reaches the goal.

## Runtime boundary

v0.2 supports Codex only. The core contract uses provider-neutral role and result terms so a later Claude adapter can reuse semantics without pretending manifests, model IDs, permissions, or limits are portable.

The skill defines required behavior. Codex and its sandbox remain responsible for documented model availability, concurrency, permissions, and approvals. CodeCanopy and the root explicitly create and verify worktree isolation where it is needed.

## Planning structures

CodeCanopy maintains:

- An ownership tree for parent authority, scope, budget, questions, and integration.
- An artifact dependency DAG for readiness and execution order.

The ownership tree is what the user sees. Only dependency-ready leaves execute. A parent is accepted only after it verifies required child artifacts, performs its own integration check, and emits one normalized result upward.

## Recursive algorithm

For every node:

1. Inspect the scoped evidence and relevant callers.
2. Apply the Leaf Test before delegation.
3. If atomic, complete the node directly.
4. Otherwise split into independently usable outcome contracts, record artifacts and dependencies, reserve parent integration capacity, and recursively plan delegation-enabled children.
5. Collapse a split when coordination cost exceeds parallel or specialist value.
6. Before dispatching a source-level leaf with accepted dependencies, have the root integrate those commits in DAG order into a fresh immutable baseline; then dispatch the deepest critical-path leaves that are ready and within all effective limits.
7. Verify and integrate accepted results bottom-up.
8. Replan only the invalid dependent subtree.
9. Stop when root acceptance passes.

## Leaf Test

A node is atomic when it has one bounded deliverable and owner, one explicit acceptance check, a coherent read or write scope, no unresolved user/product/security decision, no dependency on a sibling's unfinished output, and work that fits the remaining model and planning limits.

Never split merely into research, implementation, testing, or reporting phases when one agent can own the complete outcome.

Depth and total-node capacity apply when a node proposes children. A leaf at the configured maximum depth can still become ready when its dependencies, scope, baseline, budget, and acceptance check are valid; active-child capacity controls when that ready leaf is dispatched.

## Node contract

Each node records: ID, parent, role, objective, deliverable, non-goals, immutable baseline commit plus materialized dependency commits, read scope, write scope, produced artifacts, consumed artifacts, dependencies, acceptance check, evidence tier, model tier, remaining budget, delegation permission, stop condition, and Git mode.

Workers return: status, result, files, commit or diff, checks, evidence, and exact blocker.

## Default limits

- Root depth: 0.
- Maximum depth: 3.
- Maximum children per node: 3.
- Maximum total nodes including root: 9.
- Maximum active children: 3.
- Maximum subtree replans: 1.
- Root integration reserve: 35 percent.
- Retry limit: 1, only with new evidence.

Effective parallelism is the lower of the CodeCanopy configuration and the host limit.

## Model policy

Use capability roles in the core contract. The Codex adapter maps current preferences:

- Lead: `gpt-5.6-sol`, high reasoning.
- Expert: `gpt-5.6-terra`, high reasoning.
- Worker: `gpt-5.6-luna`, medium reasoning.
- Reviewer: `gpt-5.6-terra`, high reasoning.

The lead owns material user questions, architecture, security-sensitive decisions, integration, and replanning. Smaller models receive bounded execution. Unavailable models fall back only to a safe available tier or return to the lead; integration and review must not silently downgrade.

## Configuration

An optional project-root `.codecanopy.toml` may lower or tune planning limits and preferred model mappings. Unknown keys or invalid values are ignored with a visible warning; built-in safe defaults remain active. Precedence is host/admin policy, explicit current user instruction, project configuration, then built-in defaults.

The public v0.2 schema uses `max_parallel`, `max_replans`, `root_reserve_percent`, and `reasoning_effort`. Documentation and the bundled asset must use these exact names.

Configuration cannot grant Git, network, destructive, credential, production, or publication authority.

## Safety invariants

- Child authority never exceeds parent authority.
- One writer owns a path at a time.
- Shared files, lockfiles, generated schemas, and integration files return to the nearest common parent.
- Baseline drift or dirty overlap stops the affected lane.
- Accepted source dependencies are materialized by the root into an immutable checkpoint before a dependent leaf runs; changed dependencies invalidate affected descendants.
- Children never merge, rebase, push, open pull requests, or resolve shared conflicts.
- One evidence-based retry is allowed; repeated or semantic failure returns to the parent.
- Contract changes invalidate only dependent descendants; accepted unrelated work remains valid.
- The root alone declares the goal complete after integrated verification.

## Acceptance

- No instruction says child workers can never delegate.
- The skill explains the ownership-tree and dependency-DAG distinction.
- Recursive planning, Leaf Test, bottom-up integration, subtree replanning, and stopping rules are discoverable from `SKILL.md`.
- Configuration and Codex mapping are documented without overstating enforcement.
- Existing Git safety and evidence rules remain intact.
- Plugin and skill validators pass.
- An independent forward test produces a nested plan for a genuinely recursive request and a single-agent plan for an atomic request.
