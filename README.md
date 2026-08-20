# CodeCanopy

CodeCanopy turns an engineering requirement into the smallest useful tree of specialist and worker agents. One root lead owns scope, integration, and the final verdict; parallel writers receive isolated Git ownership.

## Install

```bash
codex plugin marketplace add adhit-r/codecanopy --ref main
codex plugin add code-canopy@codecanopy
```

Restart the Codex or ChatGPT desktop app after installation, then start a new task.

## Use

```text
Use $code-canopy to plan this engineering goal as a bounded agent tree.
```

CodeCanopy keeps small tasks single-agent, limits delegation depth and concurrency, reserves budget for root integration, and applies Ponytail's reuse-first gate to avoid overengineering.

## Safety boundary

The skill never expands the user's authority. Remote writes, destructive actions, credentials, production changes, and scope expansion require explicit approval. These instructions guide agent behavior; the host sandbox and approval policy remain the enforcement boundary.

## Support and security

- General support: [GitHub issues](https://github.com/adhit-r/codecanopy/issues)
- Security reports: follow [SECURITY.md](SECURITY.md)
- Privacy: [PRIVACY.md](PRIVACY.md)
- Terms: [TERMS.md](TERMS.md)

## License

MIT. See [LICENSE](LICENSE).
