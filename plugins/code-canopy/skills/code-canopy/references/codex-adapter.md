# CodeCanopy Codex adapter

This adapter maps the provider-neutral runtime contract to current Codex preferences. The runtime contract still defines CodeCanopy behavior; Codex and its host environment retain enforcement of their own capabilities and policy.

## Role preferences

| Role | Preferred Codex model | Reasoning |
| --- | --- | --- |
| Lead | `gpt-5.6-sol` | high |
| Expert | `gpt-5.6-terra` | high |
| Worker | `gpt-5.6-luna` | medium |
| Reviewer | `gpt-5.6-terra` | high |

Use the smallest capable tier for bounded execution. If a preferred model is unavailable, use only a safe available tier or return the work to the lead. Review and integration must not silently downgrade.

## Host boundary

CodeCanopy plans within its configured limits, but Codex and its host environment enforce documented model availability, concurrency, sandbox policy, permissions, and approvals. CodeCanopy and the root must explicitly create and verify worktree isolation where it is needed. Effective concurrency is the lower of the CodeCanopy configuration and the host limit.

No documented Codex setting enforces CodeCanopy's maximum depth or total-node limit. The planner must record and honor those limits itself; this adapter does not claim host enforcement where none is documented.

Configuration may tune planning limits and preferred model mappings. It cannot grant Git, network, destructive, credential, production, or publication authority. A child receives no authority beyond its parent, and Codex approval or sandbox enforcement remains independent of the planning contract.
