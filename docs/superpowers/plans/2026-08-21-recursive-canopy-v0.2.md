# Recursive Canopy v0.2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make CodeCanopy recursively decompose and integrate bounded Codex agent trees while retaining its existing safety boundary.

**Architecture:** Keep the plugin declarative. Put the compact routing workflow in `SKILL.md`, the provider-neutral node and scheduling contract in one reference, Codex-specific mappings in a second reference, and the user-editable sample in an asset. Do not add a scheduler, service, dependency, or persistent run store.

**Tech Stack:** Markdown, TOML, JSON manifest, bundled Python validators.

**Spec:** `docs/superpowers/specs/2026-08-21-recursive-canopy-v0.2.md`

## Global Constraints

- Codex-only execution in v0.2.
- Root depth is 0; default maximum depth is 3.
- Default maximum is 9 total nodes and 3 active children.
- Root reserves 35 percent for integration and verification.
- No configuration may expand user authority.
- No new runtime dependency, MCP server, daemon, database, or dashboard.

---

### Task 1: Recursive core contract

**Files:**
- Modify: `plugins/code-canopy/skills/code-canopy/SKILL.md`
- Create: `plugins/code-canopy/skills/code-canopy/references/runtime-contract.md`
- Create: `plugins/code-canopy/skills/code-canopy/assets/codecanopy.toml`

**Interfaces:**
- Consumes: the approved v0.2 specification and existing Ponytail gate.
- Produces: recursive node contract, Leaf Test, default limits, configuration precedence, and links to detailed runtime guidance.

- [ ] **Step 1: Rewrite the fixed-depth planning section**

Replace the fixed `depth 2` and `Child worker ... never delegates again` rules with the exact default limits from the specification and a recursion condition requiring remaining depth, remaining total-node capacity, disjoint scope, explicit acceptance, and useful parallel or specialist value.

- [ ] **Step 2: Add the user-visible operating loop**

Document: contract, candidate split, Leaf Test, ownership tree plus artifact DAG, deepest-ready leaf dispatch, bottom-up acceptance, affected-subtree replan, and root acceptance stop.

- [ ] **Step 3: Add the runtime contract reference**

Define node fields, state transitions, readiness, integration barriers, collision handling, retry behavior, subtree invalidation, normalized result, and the distinction between behavioral requirements and host enforcement. Maximum-depth capacity gates further delegation; it must not block an already-planned leaf from becoming ready.

- [ ] **Step 4: Add the TOML asset**

Ship the approved defaults under `[tree]`, `[budget]`, and the four `[models.*]` tables. Use the public keys `max_parallel`, `max_replans`, `root_reserve_percent`, and `reasoning_effort` consistently across the asset and documentation. Include only tunable limits and model preferences; omit permission or Git-authority settings.

- [ ] **Step 5: Validate the skill structure**

Run:

```bash
python3 /Users/adhi/.codex/skills/.system/skill-creator/scripts/quick_validate.py plugins/code-canopy/skills/code-canopy
```

Expected: exit 0 with a valid skill report.

### Task 2: Codex adapter and execution safety

**Files:**
- Modify: `plugins/code-canopy/skills/code-canopy/references/execution-protocol.md`
- Create: `plugins/code-canopy/skills/code-canopy/references/codex-adapter.md`

**Interfaces:**
- Consumes: node and result contract from Task 1.
- Produces: Codex model/agent mapping and bottom-up Git integration protocol used by the root.

- [ ] **Step 1: Extend dispatch and return packets**

Add produced and consumed artifacts, dependency IDs, model tier, remaining depth/node allowance, and delegation permission. Preserve the compact normalized result.

- [ ] **Step 2: Define recursive Git ownership**

State that child branches are rooted at the recorded baseline, path ownership is inherited or narrowed, shared files return to the nearest common parent, and integration follows artifact dependency order.

- [ ] **Step 3: Document Codex mapping honestly**

Map role preferences to current Codex model names, use effective concurrency as the lower host/plugin limit, and state that no documented Codex setting enforces CodeCanopy depth or total nodes.

- [ ] **Step 4: Check for unsafe or stale rules**

Run:

```bash
rg -n "never delegates|depth 2|eight total child|two waves|force-push|permission|authority|host" plugins/code-canopy/skills/code-canopy
```

Expected: no fixed non-recursive rule; safety statements remain present.

### Task 3: Package metadata and forward validation

**Files:**
- Modify: `plugins/code-canopy/.codex-plugin/plugin.json`
- Modify: `plugins/code-canopy/skills/code-canopy/agents/openai.yaml`
- Modify: `README.md`

**Interfaces:**
- Consumes: accepted Tasks 1 and 2.
- Produces: v0.2.0 package metadata, accurate public documentation, and validated behavior.

- [ ] **Step 1: Update package truth**

Set manifest version to `0.2.0`, describe recursive bottom-up orchestration, keep Codex-only wording, and point the website to `https://adhit-r.github.io/codecanopy/` once the Pages source exists.

- [ ] **Step 2: Update invocation copy**

Make the default prompt request the smallest verified recursive agent tree. Keep starter prompts at three or fewer and within manifest limits.

- [ ] **Step 3: Update README**

Describe recursive planning, `.codecanopy.toml`, honest host boundaries, the Pages URL, and unchanged installation commands.

- [ ] **Step 4: Run validators**

Run:

```bash
python3 /Users/adhi/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py plugins/code-canopy
python3 /Users/adhi/.codex/skills/.system/skill-creator/scripts/quick_validate.py plugins/code-canopy/skills/code-canopy
```

Expected: both commands exit 0.

- [ ] **Step 5: Forward-test behavior**

Give an independent agent the installed skill plus one recursive cross-component request and one atomic one-file request. Expected: the first yields nested delegation with dependency ordering; the second remains single-agent.
