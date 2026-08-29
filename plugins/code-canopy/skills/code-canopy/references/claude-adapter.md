# CodeCanopy Claude adapter

This adapter maps a node explicitly assigned `claude` to the locally installed Claude CLI. The runtime checks `claude` is available, then invokes its headless JSON mode as `claude --print --output-format json <prompt>` with the node's recorded timeout and working directory. The prompt is an argument, not shell input.

Claude model, authentication, permissions, concurrency, and worktree policy remain Claude/host concerns. CodeCanopy does not claim that Codex roles, model preferences, limits, approval behavior, or manifests are portable to Claude. A writing node still receives a caller-created detached Git worktree and must pass the provider-neutral acceptance barrier.

If `claude` is unavailable, the local adapter may run Codex only when its CLI is available. That result records `requested_provider: claude`, `provider: codex`, `fallback_used: true`, and the reason. It never transfers credentials, and it never silently downgrades a node. A successful headless run proves only that local invocation completed; it is not a quality, production, or cross-provider-equivalence claim.
