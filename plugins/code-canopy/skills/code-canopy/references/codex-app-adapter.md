# Codex app task and cross-provider adapter

This adapter defines how a CodeCanopy root may coordinate independent Codex app tasks alongside the existing local Codex and Claude CLI adapters. It is a planning and evidence contract, not a claim that the local Python runtime can create app tasks.

## Separate execution surfaces from providers

Record `execution_surface` independently from `provider`:

| Execution surface | Meaning | Provider and model evidence |
|---|---|---|
| `codex_app_task` | A user-visible Codex app task created by the root for one independent branch | Omit `provider`; separate `actual_model` is host-reported or `unknown` |
| `local_cli` | The existing bounded `ProviderRequest` subprocess path | Requested and actual `codex` or `claude`; separate model when reported |
| `future_adapter` | A separately implemented and reviewed provider adapter | Adapter-reported provider and separate model |

A Codex app task is not a `codex exec` subprocess. Never attach CLI receipts, Claude-to-Codex fallback rules, or inherited credentials to it. A future provider is unsupported until its adapter has an allowlisted executable, capability check, bounded request and result, credential boundary, timeout, isolation policy, and proof format. Configuration cannot introduce an arbitrary command or declare an adapter trusted.

## Authorization and fanout

Native app tasks are created only after the user explicitly asks to create tasks or approves that fanout. A CodeCanopy plan by itself is not authorization to create a user-visible task.

Before dispatch, the root verifies that the host exposes native create, read, message, and wait lifecycle capabilities. If any required capability is unavailable, mark `codex_app_task` unavailable and keep the work at the root or choose another already-authorized surface. Never simulate an app task with a local CLI run or claim cross-task coordination from a subprocess.

Branch fanout requires a saved Git project and a host-created worktree. Reject projectless, local-checkout, and same-directory targets for writing tasks. A queued client task is not ready: do not message or count it active until the host returns a usable task ID. Before source edits, the root requires the task to report its registered branch-attached worktree, repository identity, assigned branch, and `HEAD`; dispatch stops unless the branch equals the recorded assignment and `HEAD` equals the recorded immutable baseline. A host-created worktree does not replace baseline verification.

The root is the only task creator, messenger, handoff or cancel actor, Git integrator, and acceptor. The first app adapter does not permit nested app-task creation: child tasks return evidence to the root and cannot create peers, expand scope, change provider, grant permissions, or accept their own work.

Create at most one live app task for one independent branch. A writing task receives exclusive ownership of its repository, branch, branch-attached worktree, immutable baseline, and path scope. Sibling tasks never share writable paths, worktrees, branches, manifests, lockfiles, generated schemas, or integration files. App fanout remains inside the existing depth, total-node, active-child, replan, and root-reserve limits; the host may impose a lower effective limit.

If branch or worktree creation, source writes, or app-task creation is not authorized, keep the work at the root or use a read-only local lane.

## Cross-family collaboration

Codex, Claude, and future providers collaborate through normalized artifacts, not shared transcripts or credentials. A sibling may consume only an accepted predecessor artifact that the root has reviewed and materialized into a new immutable baseline. Provider selection is recorded before dispatch and fallback fails closed.

Every returned packet identifies the execution surface, requested and actual provider when applicable, a separate actual model when the host reports it, baseline, commit or diff, checks, bounded evidence references, status, and blocker. App-task packets omit `provider`; missing model evidence is `unknown`, never inferred from prose. The root verifies the packet before forwarding a narrow artifact reference to another provider.

This makes mixed execution possible without claiming provider equivalence. For example, one branch may run as a Codex app task while an independent sibling uses the local Claude CLI. Both return through the same parent acceptance barrier; neither receives the other's credentials, raw prompt, full output, or authority.

## Team-room projection

Do not let multiple tasks append to or edit one Markdown file. Concurrent shared-file writes create collisions and allow a child to present text as accepted state.

When durable human-readable coordination is useful and repository writes are authorized, the root may generate a root-owned `team-room.md` projection from its observations. Children never write it directly. Use a caller-approved state path, refuse symlinks and special files, and never overwrite an unrelated or dirty user file. Record only bounded events such as `dispatched`, `returned`, `blocked`, `verified`, and `accepted`, with opaque task IDs, branch and baseline identifiers, summaries, and evidence references. Exclude raw prompts, transcripts, provider output, secrets, credentials, and child-authored instructions. The projection is status context, not an authenticated ledger, permission source, or acceptance proof.

Root-to-task messages carry narrow evidence pointers or questions only. A message cannot alter the goal, permissions, provider, Git mode, path ownership, or acceptance check without a new root decision grounded in current user authority.
