# CodeCanopy

CodeCanopy is a Codex engineering orchestration plugin. It turns a requirement into the smallest verified recursive agent tree, runs only dependency-ready leaves, and integrates evidence bottom-up under one accountable lead.

[Website](https://adhit-r.github.io/codecanopy/) · [Current work](https://github.com/adhit-r/codecanopy/issues/1) · [Good first issue](https://github.com/adhit-r/codecanopy/issues/3)

## Install

```bash
codex plugin marketplace add adhit-r/codecanopy --ref main
codex plugin add code-canopy@codecanopy
```

Restart the Codex or ChatGPT desktop app after installation, then start a new task.

## Use

```text
Use $code-canopy to plan this engineering goal as the smallest verified recursive agent tree.
```

## How Recursive Canopy works

CodeCanopy keeps two structures separate:

- The ownership tree records who owns scope, delegation, questions, and integration.
- The artifact dependency graph records which verified outputs must exist before a leaf can run.

The root applies a Leaf Test before delegation. Atomic work stays with one agent. Non-atomic work splits only into independently verifiable outcomes, runs from the deepest dependency-ready frontier, and returns upward through parent acceptance checks. Before dependent source work runs, the root materializes its accepted predecessors into an immutable baseline. Changed contracts invalidate only dependent descendants.

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
runtime = "codex"

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

## Safety boundary

The skill never expands the user's authority. Remote writes, destructive actions, credentials, production changes, and scope expansion require explicit approval. CodeCanopy and the root create and verify worktree isolation where needed; the host retains its documented sandbox, approval, model, and concurrency boundaries.

## Roadmap

- Current: [Recursive Canopy v0.2](https://github.com/adhit-r/codecanopy/issues/1) and [public Pages documentation](https://github.com/adhit-r/codecanopy/issues/2).
- Next: [Claude Code provider adapter](https://github.com/adhit-r/codecanopy/issues/4).
- Research: [mixed Codex CLI and Claude Code CLI trees](https://github.com/adhit-r/codecanopy/issues/5).
- Evidence-gated: [resumable run manifests and proof history](https://github.com/adhit-r/codecanopy/issues/6).

A deterministic scheduler remains deferred until real runs show that the declarative contract cannot honor limits or resume reliably.

## Contributing

Start with the [good first issue](https://github.com/adhit-r/codecanopy/issues/3) or another open issue, then read [CONTRIBUTING.md](CONTRIBUTING.md). Small, verified changes are preferred over new infrastructure.

## Support and security

- General support: [GitHub issues](https://github.com/adhit-r/codecanopy/issues)
- Security reports: follow [SECURITY.md](SECURITY.md)
- Privacy: [PRIVACY.md](PRIVACY.md)
- Terms: [TERMS.md](TERMS.md)

## License

MIT. See [LICENSE](LICENSE).
