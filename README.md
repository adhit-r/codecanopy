# CodeCanopy

CodeCanopy is an engineering orchestration plugin with local runtime support for provider-neutral node records. It turns a requirement into the smallest verified recursive agent tree, runs only dependency-ready leaves, and integrates evidence bottom-up under one accountable lead.

[Website](https://adhit-r.github.io/codecanopy/) · [Current work](https://github.com/adhit-r/codecanopy/issues/1) · [Good first issue](https://github.com/adhit-r/codecanopy/issues/3)

## Install

```bash
codex plugin marketplace add adhit-r/codecanopy --ref main
codex plugin add code-canopy@codecanopy
```

Restart the Codex or ChatGPT desktop app after installation, then start a new task.
The marketplace package installs the skill. The optional Python runtime commands
below currently require a repository checkout; packaging that runtime is the
next release gate.

## Use

```text
Use $code-canopy to plan this engineering goal as the smallest verified recursive agent tree.
```

## How Recursive Canopy works

CodeCanopy keeps two structures separate:

- The ownership tree records who owns scope, delegation, questions, and integration.
- The artifact dependency graph records which verified outputs must exist before a leaf can run.

The root applies a Leaf Test before delegation. Atomic work stays with one agent. Non-atomic work splits only into independently verifiable outcomes, runs from the deepest dependency-ready frontier, and returns upward through parent acceptance checks. Before dependent source work runs, the root materializes its accepted predecessors into an immutable baseline. Changed contracts invalidate only dependent descendants.

During planning, CodeCanopy estimates each node's normalized complexity and size, computes the weighted routing score from `.codecanopy.toml`, and automatically selects the smallest configured tier allowed by policy. Simple bounded work routes to `worker`, medium work to `expert`, and complex or safety-sensitive work to `lead`; review work routes to `reviewer`, and uncertain work never routes below `expert`. The checked-in deterministic policy benchmark currently passes 10/10 routing cases, rejects 3/3 invalid estimates, and gives 6/10 fixture cases non-lead assignments. It is not evidence of model quality, token savings, latency, or throughput. Run it with `python3 benchmarks/model_routing.py`; use the [paired benchmark contract](benchmarks/README.md) before making comparative claims.

### Automatic model resolution

For each new run, CodeCanopy scores a node, chooses its role tier, resolves the provider-released and account-available catalog once, freezes its catalog hash, dispatches an exact Codex ID or a Claude alias, and records observed model evidence. That frozen catalog remains in effect through execution and resume: a future host default or lower-capability entry can be selected only by the next new run, never midway through a tree. A malformed or incomplete catalog blocks dispatch. Codex exact IDs come from authenticated structured host metadata; Claude aliases are dispatched directly and an exact backing ID is recorded only when `modelUsage` evidences it. Previews are not intentionally selected. These controls do not claim universal provider availability or model quality.

```text
Goal lead
├─ Architecture parent
│  ├─ Contract leaf
│  └─ Evidence leaf
└─ Implementation parent       after Architecture
   ├─ Backend leaf
   └─ Interface leaf           after Backend
```

## Configuration

Copy the bundled [`codecanopy.toml`](plugins/code-canopy/skills/code-canopy/assets/codecanopy.toml) to `.codecanopy.toml` in a project root when the defaults need tuning:

```toml
schema_version = 1
runtime = "local"

[model_discovery]
mode = "automatic"
release_channel = "ga"
refresh = "run_start"
on_failure = "fail"

[tree]
max_depth = 3
max_children_per_node = 3
max_total_nodes = 9
max_parallel = 3
max_replans = 1

[budget]
root_reserve_percent = 35
retry_limit = 1

[models.lead]
model = "auto"
reasoning_effort = "high"

[models.expert]
model = "auto"
reasoning_effort = "high"

[models.worker]
model = "auto"
reasoning_effort = "medium"

[models.reviewer]
model = "auto"
reasoning_effort = "high"
```

The strongest configured tier owns requirements, material questions, integration, and replanning. Smaller configured tiers receive bounded work. Model availability and host limits still apply.

Provider and timeout are per-node values, not TOML settings. Local support checks an installed CLI, prepends a fixed trust boundary, and invokes Codex or Claude without a shell. Delegated Codex runs ignore user config and rules, disable project instruction loading and workspace network, prevent login shells, strip the child-shell environment, require the configured sandbox, and persist no session. Claude runs in safe, non-persistent mode with only bounded file tools; customizations, Bash, agents, browser, slash-command, web, and MCP tools are unavailable. The root runs acceptance checks. Fallback is denied by default; unavailable Claude work reaches Codex only after explicit CLI consent. The provider subprocess receives an allowlisted environment and bounded output capture. CodeCanopy does not claim that provider policies or model quality are equivalent.

## Safety boundary

The skill never expands the user's authority. Repository instructions, code comments, issues, logs, web content, attachments, and child output are untrusted task data: they cannot request secrets, enable network, change provider, bypass approvals, or authorize destructive or remote Git actions. CodeCanopy and the root create and verify worktree isolation where needed; the local helper never merges, commits, or pushes.

Local manifests and proof receipts are owner-only, symlink-safe, size-bounded JSONL evidence. Manifests store prompt hashes rather than raw prompts and validate lifecycle replay. Accepted state is never reused across invocations until keyed integrity exists. Worktree reuse verifies Git registration, repository identity, detached state, and baseline. This is local runtime support, not a cryptographically authenticated audit trail, durable scheduler, secret store, or proof of provider quality.

### Coordinate Codex app tasks and model families

CodeCanopy may plan one user-visible Codex app task per independent branch only after the user explicitly authorizes task creation. App-task fanout is a host-native execution surface, not the local `codex exec` provider path: the root alone creates tasks, messages them, verifies returned commits and checks, and accepts work. The initial contract forbids nested app-task creation and shared writable paths.

Codex app tasks, local Codex CLI nodes, and local Claude CLI nodes collaborate through root-verified commits, artifacts, checks, and normalized result packets. They do not share raw transcripts or credentials. A human-readable `team-room.md`, when requested and authorized, is generated only by the root from bounded status observations; children never edit it concurrently. Other model families remain unsupported until an allowlisted adapter defines capability, isolation, credential, timeout, and proof boundaries. See the [Codex app task and cross-provider adapter](plugins/code-canopy/skills/code-canopy/references/codex-app-adapter.md).

### Run a mixed-provider tree locally

The runtime accepts a small JSON plan. Each node names its provider and dependencies; the runner records results, receipts, and recovery state without merging or pushing:

```json
{
  "run_id": "mixed-example",
  "nodes": [
    {"id": "contract", "provider": "codex", "prompt": "Define the contract."},
    {"id": "backend", "provider": "codex", "depends_on": ["contract"], "dependency_commits": {"contract": "1111111111111111111111111111111111111111"}, "prompt": "Implement the backend."},
    {"id": "ui", "provider": "claude", "depends_on": ["contract"], "dependency_commits": {"contract": "1111111111111111111111111111111111111111"}, "prompt": "Implement the UI."}
  ]
}
```

Replace the example dependency SHA with the accepted predecessor commit already materialized in each dependent node's baseline; every dependency requires an exact immutable mapping. Run it with `python3 -m runtime.tree plan.json --manifest .codecanopy/run.jsonl --repo . --worktree-root .worktrees --receipt-dir .codecanopy/receipts --accept-completed` only when a successful CLI exit is the explicit leaf check. Trusted filesystem roots are CLI arguments and are rejected inside the JSON plan. Without `--accept-completed`, results remain `returned`. Add `--allow-provider-fallback` only when unavailable Claude work may be disclosed to Codex. Completed manifests remain inspectable but cannot authorize another execution.

Inspect an existing local run without dispatching a provider:

```bash
python3 -m runtime.tree --status --manifest .codecanopy/run.jsonl --run-id mixed-example
python3 -m runtime.tree --inspect ui --manifest .codecanopy/run.jsonl --run-id mixed-example
```

`--status` reports node counts and the dependency-ready critical frontier;
`--inspect` prints the recorded contract, checks, and invalidations for one
node. These are local manifest views, not proof that a goal is accepted.

## Roadmap

- Current release: v0.5.0 adds automatic, run-frozen provider catalog resolution while retaining the existing safety boundaries. See [CHANGELOG.md](CHANGELOG.md).
- Next: package the local runtime with the marketplace artifact, add a pinned release workflow, and verify the installed plugin from a clean archive.
- In progress: run observability now includes `--status` and `--inspect` for reconstructing the critical frontier from a manifest.
- Tracked work: [public Pages documentation](https://github.com/adhit-r/codecanopy/issues/2), [current work](https://github.com/adhit-r/codecanopy/issues/1), and the provider/recovery issues [#4](https://github.com/adhit-r/codecanopy/issues/4), [#5](https://github.com/adhit-r/codecanopy/issues/5), and [#6](https://github.com/adhit-r/codecanopy/issues/6).
- Evidence-gated: real-provider quality, comparative token and wall-clock gains, production behavior, and durable multi-process recovery remain unclaimed until separately observed.

A deterministic scheduler remains deferred until real runs show that the local contract cannot honor limits or recovery requirements.

## Contributing

Start with the [good first issue](https://github.com/adhit-r/codecanopy/issues/3) or another open issue, then read [CONTRIBUTING.md](CONTRIBUTING.md). Small, verified changes are preferred over new infrastructure.

## Support and security

- General support: [GitHub issues](https://github.com/adhit-r/codecanopy/issues)
- Security reports: follow [SECURITY.md](SECURITY.md)
- Privacy: [PRIVACY.md](PRIVACY.md)
- Terms: [TERMS.md](TERMS.md)

## License

MIT. See [LICENSE](LICENSE).
