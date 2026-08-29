# Changelog

All notable CodeCanopy changes are recorded here. Version entries describe
implemented local behavior only; provider quality, production behavior, and
durable multi-process recovery remain evidence-gated.

## [Unreleased]

- Add release automation and additional integration checks as they become
  accepted roadmap work.

## [0.3.0] - 2026-08-29

### Added

- Local provider-neutral execution for per-node Codex CLI and Claude Code CLI
  requests.
- Explicit Claude-to-Codex fallback only when the Claude executable is
  unavailable, with the requested provider, actual provider, reason, and
  fallback recorded in the result and proof receipt.
- Capability checks, bounded timeouts, detached worktree preparation, and
  hash-only proof receipts.
- Append-only JSONL manifests for interrupted-run recovery, immutable baseline
  checks, dependency checks, and downstream invalidation.
- Mixed-provider tree coverage and deterministic weighted model-routing
  benchmark coverage.

### Safety and boundaries

- Failed or timed-out provider runs never silently switch providers.
- Local runtime support does not merge, commit, push, share credentials, or
  claim provider equivalence, production readiness, or model quality.

## [0.2.0] - 2026-08-21

- Recursive Canopy core: bounded ownership trees, artifact dependency ordering,
  bottom-up acceptance, weighted model routing, and Git safety boundaries.
- Public GitHub Pages documentation and contributor guidance.
