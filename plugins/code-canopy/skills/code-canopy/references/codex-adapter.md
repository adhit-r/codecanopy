# CodeCanopy Codex adapter

This adapter maps the provider-neutral runtime contract to current Codex preferences. The local runtime invokes Codex headlessly with `codex exec --json --sandbox <read-only|workspace-write> --ephemeral` after its capability check and within the recorded timeout. It ignores user config and execution rules, disables project instruction loading and workspace network, uses a never-escalate approval policy, strips the child-shell environment, and disallows login shells. Write access is selected only for an isolated writing worktree. The runtime contract still defines CodeCanopy behavior; Codex and its host environment retain enforcement of their own capabilities and policy.

## Role preferences

| Role | Codex selector | Reasoning |
| --- | --- | --- |
| Lead | `auto` | high |
| Expert | `auto` | high |
| Worker | `auto` | medium |
| Reviewer | `auto` | high |

Use the smallest capable tier for bounded execution. At new-run start and before manifest creation, CodeCanopy asks authenticated structured host metadata for the provider-released, account-available catalog exactly once, chooses exact IDs, and freezes their source metadata and catalog hash through execution and resume. A malformed or incomplete catalog blocks dispatch. Previews are not intentionally selected. A changed host default or lower-capability entry is considered only on a new run, never midway through a tree. Review and integration must not silently downgrade.

## Automatic routing

The planner assigns every node normalized complexity and size scores, then applies `[routing]` from `codecanopy.toml` without a human model choice. The weighted score selects `worker` for simple bounded work, `expert` for medium work, and `lead` for complex work. Root, integration, and security-sensitive decisions override the score to `lead`; review work selects `reviewer`; uncertain signals select at least `expert`.

The routing score is a planning decision, not a host capability claim. Codex still decides whether a configured model is available. If a frozen exact model is unavailable, block the node. A different exact model requires explicit user authorization for that transition and a new frozen execution contract.

## Host boundary

CodeCanopy plans within its configured limits, but Codex and its host environment enforce documented model availability, concurrency, sandbox policy, permissions, and approvals. CodeCanopy and the root must explicitly create and verify worktree isolation where it is needed. Effective concurrency is the lower of the CodeCanopy configuration and the host limit.

No documented Codex setting enforces CodeCanopy's maximum depth or total-node limit. The planner must record and honor those limits itself; this adapter does not claim host enforcement where none is documented.

Configuration may tune planning limits and preferred model mappings. It cannot grant Git, network, destructive, credential, production, or publication authority. A child receives no authority beyond its parent, and Codex approval or sandbox enforcement remains independent of the planning contract.

Codex is the explicit recorded fallback only for a Claude node whose CLI executable is unavailable and whose caller authorized that exact transition before dispatch. The receipt identifies both requested and actual provider; the subprocess environment allowlist never transfers Claude credentials.
