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

During planning, CodeCanopy estimates each node's normalized complexity and size, computes the weighted routing score from `.codecanopy.toml`, and automatically selects the smallest capable configured tier. Simple bounded work routes to `worker`, medium work to `expert`, and complex or safety-sensitive work to `lead`; review work routes to `reviewer`, and uncertain work never routes below `expert`. The checked-in deterministic policy benchmark currently passes 10/10 routing cases and rejects 3/3 invalid estimates; it is not a model-quality or latency benchmark. Run it with `python3 benchmarks/model_routing.py`.

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

[tree]
max_depth = 3
max_children_per_node = 3
max_total_nodes = 9
max_parallel = 3
max_replans = 1

[budget]
root_reserve_percent = 35
retry_limit = 1
```

The strongest configured tier owns requirements, material questions, integration, and replanning. Smaller configured tiers receive bounded work. Model availability and host limits still apply.

Provider and timeout are per-node `ProviderRequest` values, not TOML settings. Local support checks an installed CLI, then invokes either `codex exec --json` or `claude --print --output-format json` without a shell. The only fallback is an unavailable Claude executable to Codex, and the result/receipt flags it. Local support does not copy credentials, choose a provider silently, or claim that provider policies or model quality are equivalent.

## Safety boundary

The skill never expands the user's authority. Remote writes, destructive actions, credentials, production changes, and scope expansion require explicit approval. CodeCanopy and the root create and verify worktree isolation where needed; the local helper creates detached worktrees under a caller-owned root and never merges, commits, or pushes. The host retains its documented sandbox, approval, model, and concurrency boundaries.

Local manifests and proof receipts are append-only JSONL evidence for interrupted-run recovery. Recovery never marks work successful; the parent rechecks the immutable baseline, dependencies, worktree, and evidence before dispatch, otherwise invalidating only downstream nodes. This is local runtime support, not a durable scheduler, distributed lock, secret store, production audit trail, or proof of provider quality.

### Run a mixed-provider tree locally

The runtime accepts a small JSON plan. Each node names its provider and dependencies; the runner records results, receipts, and recovery state without merging or pushing:

```json
{
  "run_id": "mixed-example",
  "nodes": [
    {"id": "contract", "provider": "codex", "prompt": "Define the contract."},
    {"id": "backend", "provider": "codex", "depends_on": ["contract"], "prompt": "Implement the backend."},
    {"id": "ui", "provider": "claude", "depends_on": ["contract"], "prompt": "Implement the UI."}
  ]
}
```

Run it with `python3 -m runtime.tree plan.json --manifest .codecanopy/run.jsonl --accept-completed` only when a successful CLI exit is the explicit leaf check. Without that flag, results remain `returned` until the parent runs its acceptance check. If a node omits `baseline`, the runner resolves the current Git revision to a full commit before recording or dispatching it. Add `repo` and `worktree_root` to the plan for detached Git worktrees. A missing Claude CLI may use Codex only when the result records the fallback; failures and timeouts never switch providers.

Inspect an existing local run without dispatching a provider:

```bash
python3 -m runtime.tree --status --manifest .codecanopy/run.jsonl --run-id mixed-example
python3 -m runtime.tree --inspect ui --manifest .codecanopy/run.jsonl --run-id mixed-example
```

`--status` reports node counts and the dependency-ready critical frontier;
`--inspect` prints the recorded contract, checks, and invalidations for one
node. These are local manifest views, not proof that a goal is accepted.

## Roadmap

- Current release: v0.3.0 adds local mixed-provider execution, append-only recovery manifests, proof receipts, and the weighted routing benchmark. See [CHANGELOG.md](CHANGELOG.md).
- Next: package the local runtime with the marketplace artifact, add a pinned release workflow, and verify the installed plugin from a clean archive.
- In progress: run observability now includes `--status` and `--inspect` for reconstructing the critical frontier from a manifest.
- Tracked work: [public Pages documentation](https://github.com/adhit-r/codecanopy/issues/2), [current work](https://github.com/adhit-r/codecanopy/issues/1), and the provider/recovery issues [#4](https://github.com/adhit-r/codecanopy/issues/4), [#5](https://github.com/adhit-r/codecanopy/issues/5), and [#6](https://github.com/adhit-r/codecanopy/issues/6).
- Evidence-gated: real-provider quality, production behavior, and durable multi-process recovery remain unclaimed until separately observed.

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
