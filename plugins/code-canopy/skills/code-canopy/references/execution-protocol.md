# CodeCanopy execution protocol

Read this only when a canopy node will modify a repository or create a commit.

## Dispatch packet

Send only: node and parent IDs; objective, deliverable, and non-goals; baseline commit; relevant paths and evidence; produced and consumed artifacts; dependency IDs; write scope; acceptance check; model tier; remaining depth, node, active-child, and budget allowance; delegation permission; and stop condition. Do not copy the full transcript by default. Point to files and line ranges; store long logs as artifacts.

Workers return only:

```text
status: done | blocked | no-change
result: <one sentence>
files: <paths or none>
commit: <sha or none>
checks: <command and result>
evidence: <path:line or artifact>
blocker: <exact obstacle or none>
```

Stop a lane when its check passes. Retry a transient failure once only when new evidence justifies it. Send contradictory reports to one reviewer; do not fan out again.

## Git isolation and ownership

- Preserve unrelated dirty changes. Stop if they overlap assigned paths.
- In `edit` mode, workers stay read-only and return scoped patch instructions; the root alone edits. Use isolated writing workers only in `local-commit` or `remote` mode.
- Give each writer a unique branch and worktree rooted at the recorded baseline. Child branches remain rooted at that baseline until their parent integrates them.
- One writer owns a path. A child inherits its parent's path ownership and may narrow it, never expand it. Shared files return to the nearest common parent: this includes manifests, lockfiles, generated schemas, and integration files.
- A worker edits only its scope, inspects its diff, runs its check, and creates one focused commit only in `local-commit` or `remote` mode. It never merges, rebases, pushes, or opens a pull request.
- A parent reviews each accepted child diff and baseline before integrating it in artifact dependency order; the root performs the final integration. Never resolve conflicts by taking `ours` or `theirs` wholesale.
- Never clean, reset, restore user files, delete branches or worktrees, force-push, alter remotes, expose secrets, or run destructive migrations without explicit target-specific authorization.

## Integration and evidence

Recheck the baseline and changed paths before integration. Reject scope creep, secrets, unrelated generated files, and ownership collisions. Run each node's check, then the goal-level checks on the integrated state. Keep evidence tiers explicit.

If an assigned path is already dirty, the baseline changed, a worker crosses scope, a conflict lacks a clear semantic resolution, or required authorization is missing, stop that lane and return the exact obstacle. The root alone decides whether the goal is complete.
