# Contributing to CodeCanopy

CodeCanopy prefers the smallest verified contribution that closes one issue.

## Choose work

1. Start with an [open issue](https://github.com/adhit-r/codecanopy/issues), especially the [good first issue](https://github.com/adhit-r/codecanopy/issues/3).
2. Comment with the outcome and files you plan to own before editing shared files.
3. Keep one issue per pull request. Do not add a scheduler, service, database, dashboard, analytics, or provider claim without an accepted issue and evidence that the current contract is insufficient.

## Make the change

- Preserve unrelated work and never commit secrets or private repository data.
- Keep Codex-only behavior separate from Claude and mixed-provider roadmap work.
- Use one writer per path. Shared manifests and integration files stay with the integrating owner.
- Add the smallest runnable check for non-trivial behavior.
- Keep documentation truthful about local, staging, and production evidence.

## Verify

Run the checks that cover your change. For plugin contract or metadata changes, run:

```bash
python3 /Users/adhi/.codex/skills/.system/skill-creator/scripts/quick_validate.py plugins/code-canopy/skills/code-canopy
python3 /Users/adhi/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py plugins/code-canopy
git diff --check
```

If those absolute validator paths are unavailable, note that in the pull request and include the checks you could run.

## Pull request

Describe the result, files changed, checks, evidence level, and remaining risk. A passing local check is local evidence; it is not deployment proof.
