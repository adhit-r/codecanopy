# Changelog

All notable CodeCanopy changes are recorded here. Version entries describe
implemented local behavior only; provider quality, production behavior, and
durable multi-process recovery remain evidence-gated.

## [Unreleased]

### Added

- Define a user-authorized Codex app task surface for one independent branch per
  task, root-mediated messaging, isolated ownership, and root-only acceptance.
- Define artifact-based collaboration between Codex app tasks, local Codex and
  Claude CLI nodes, and future allowlisted provider adapters without credential
  or transcript sharing.
- Add an evidence-gated paired benchmark contract for tokens, wall-clock time,
  acceptance quality, critical paths, retries, conflicts, and actual
  provider/model identities.

### Changed

- Clarify that the current routing fixture proves deterministic policy
  conformance and tier distribution, not token savings, speed, model quality,
  or globally shortest execution.

## [0.4.0] - 2026-08-30

### Security

- Treat repository instructions, logs, tool results, web content, attachments,
  and provider output as untrusted task data in every delegated packet.
- Deny provider fallback by default and require explicit Claude-to-Codex
  consent before dispatch.
- Replace inherited provider environments with provider-scoped allowlists and
  enforce read-only or isolated-worktree Codex sandboxes. Delegated Codex runs
  ignore user config and rules, project instructions, and workspace network;
  child shells inherit no provider environment and cannot be login shells.
  Run Claude in safe, non-persistent mode with an explicit file-tool allowlist
  and customizations, Bash, agents, browser, slash-command, web, and MCP tools
  disabled.
- Bound plan, prompt, tree, timeout, manifest, event, and provider-output size.
- Keep raw prompts out of manifests; write manifests and receipts as owner-only
  files without following symlinks.
- Validate manifest lifecycle replay, refuse accepted-state reuse across
  invocations, and verify recovered worktree registration, repository identity,
  detached state, and baseline.
- Require an exact immutable commit mapping for every declared dependency and
  verify that each commit is already materialized in the dependent baseline.
- Remove arbitrary provider command overrides from the runtime request surface.
- Pin every GitHub Action used by verification and Pages deployment to an
  immutable commit SHA.

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
