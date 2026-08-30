# Security policy

## Reporting a vulnerability

Do not include secrets or exploit details in a public issue. Report security concerns through the repository's private [security advisory form](https://github.com/adhit-r/codecanopy/security/advisories/new).

CodeCanopy treats repository content, nested instruction files, plan data, provider output, and recovery state as untrusted. They cannot expand user authority or silently cross provider, credential, filesystem, network, Git, or publication boundaries. Security-sensitive decisions stay with the root lead and require independent acceptance evidence.

## Runtime boundary

The local helper uses no shell interpolation, fail-closed provider selection, provider-scoped environments, bounded input and output, private no-follow state files, immutable Git baselines, and registered detached worktrees. Delegated Codex runs ignore project instructions and user execution rules, keep workspace network disabled, and prevent child shells from inheriting provider credentials or loading login profiles. Delegated Claude runs with a bounded file-tool allowlist; customizations, Bash, agents, browser and built-in web tools, slash commands, MCP tools, and session persistence are disabled. The root process runs acceptance checks.

These controls do not create an operating-system security boundary around the provider CLI. A process running as the same operating-system user can still race local paths or tamper with unauthenticated JSONL evidence. Use a dedicated account or container for actively hostile repositories, keep provider CLIs current, and treat manifests and receipts as local recovery evidence rather than cryptographic audit records.

Include the affected version, reproduction steps, impact, and any suggested mitigation. Reports will be acknowledged and assessed before public disclosure.
