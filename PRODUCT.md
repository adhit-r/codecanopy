# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Delegated by the user's request for a small GitHub Pages site: static HTML and CSS with no runtime dependencies.

## Users

Software engineers using Codex who need to turn a non-trivial engineering requirement into bounded specialist and worker tasks without losing ownership, evidence, or Git safety.

## Product Purpose

CodeCanopy helps a lead agent form the smallest useful engineering team, execute dependency-ready work, integrate evidence bottom-up, and stop when the requested goal is verified.

## Positioning

CodeCanopy optimizes for the smallest verified path to completion rather than the largest swarm. It keeps delegation authority in an ownership tree while ordering work through artifact dependencies.

## Operating Context

CodeCanopy is distributed as a Codex plugin containing an engineering orchestration skill. It is used inside repositories where agents may investigate, edit isolated paths, run checks, and return evidence or commits to one integrating lead.

## Capabilities and Constraints

- The plugin runs as a Codex skill; its local runtime accepts per-node Codex or
  Claude CLI requests when those executables are installed.
- The skill guides recursive decomposition, model routing, Git isolation, verification, and bottom-up integration.
- A declarative plugin cannot itself guarantee worktree isolation; CodeCanopy and the root arrange and verify worktrees where needed. The host enforces documented sandbox, approval, model-availability, and concurrency boundaries. Configuration and plans cannot grant remote authorization.
- Project teams may supply `.codecanopy.toml` to lower or tune planning limits and preferred model mappings.
- Claude support is local adapter support, not a claim of provider equivalence,
  production readiness, or model quality.

## Brand Commitments

- Product name: CodeCanopy.
- Voice: direct, engineering-led, evidence-based, and free of hype.
- No emoji, purple gradients, or generic AI-product visual language.
- The public site remains small, fast, and understandable without JavaScript.

## Evidence on Hand

- Plugin source: `plugins/code-canopy/`.
- Current installation and safety statements: `README.md`.
- Public repository: `https://github.com/adhit-r/codecanopy`.
- No customer logos, testimonials, usage metrics, or production-performance benchmarks are available and none may be fabricated.

## Product Principles

- Use one agent when one agent is enough.
- Split only independently verifiable outcomes.
- Make authority and artifact dependencies explicit.
- Preserve one integration owner and proof before completion.
- Never let configuration or delegation expand user authority.
