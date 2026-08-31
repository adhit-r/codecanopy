# GA-Aware Model Resolution Design

**Status:** Approved for implementation on 2026-08-31

## Goal

CodeCanopy must stop treating bundled versioned model IDs as permanent role assignments. At the start of each tree run, the root resolves the strongest, balanced, and economical models that the active provider exposes to the current user, freezes that resolution for the run, and records enough evidence to reproduce or reject a resume.

The routing score still chooses `worker`, `expert`, `lead`, or `reviewer`. This feature changes how those tiers resolve to provider models.

## Non-goals

- Do not scrape documentation, rank semantic versions, or infer capability from model names.
- Do not switch a running tree to a newly released model.
- Do not silently downgrade a model, provider, or reasoning effort.
- Do not send credentials, the provider catalog, or ambient configuration to child agents.
- Do not add a network service, third-party dependency, or CodeCanopy-maintained release database.

## Release and availability truth

“Generally available” has two operational gates:

1. **Provider-released:** the provider exposes the model through its supported current-model mechanism rather than a hidden, specialty, or superseded entry.
2. **Account-available:** the current authenticated host exposes or resolves the model for this user and organization.

CodeCanopy can prove those gates only to the extent the provider surface attests them. It must describe Codex entries as `provider-released/account-available` rather than claim a universal public GA date. Claude aliases are provider-maintained selectors; their backing model is recorded from provider result evidence when the CLI reports it.

Preview, hidden, specialty, superseded, unavailable, or unverified entries are ineligible for general engineering routing. A future provider field that explicitly identifies release stage may tighten this gate without changing the role resolver.

## Provider discovery contracts

### Codex

The root starts the installed `codex app-server --stdio` process with a bounded allowlisted environment and performs this JSON-RPC exchange:

1. `initialize`
2. `initialized`
3. `model/list` with `includeHidden: false` and `limit: 100`

The response is account-scoped and supplies structured fields including `model`, `hidden`, `availabilityNux`, `isDefault`, `modelSpecialty`, `upgrade`, and `supportedReasoningEfforts`.

An eligible Codex entry must:

- have a valid provider model identifier;
- be visible;
- have no availability notice;
- have no specialty for the general engineering roles;
- have no provider-declared upgrade target;
- support the configured reasoning effort for the role.

Role resolution uses only structured provider metadata and provider ordering:

- `lead`: the unique eligible general entry marked `isDefault`;
- `expert` and `reviewer`: the first eligible non-default general entry supporting `ultra`;
- `worker`: the first eligible non-default general entry supporting `max` but not `ultra`.

The provider’s returned order is the tie-breaker. If any required role has no eligible candidate, discovery fails closed. The resolver never falls back to a model by parsing its ID, display name, or prose description.

### Claude Code

Claude Code does not expose the same machine-readable account catalog. Its supported aliases are the provider-owned current-model mechanism:

- `lead`: `best`;
- `expert` and `reviewer`: `sonnet`;
- `worker`: `haiku`.

CodeCanopy freezes these aliases for the run, passes them using `--model`, and passes the configured common effort using `--effort`. The proof receipt records the requested alias and, when Claude JSON contains exactly one valid `modelUsage` key, the actual backing model. Provider fallback remains disabled; a missing or disallowed alias blocks the node.

The exact Claude backing ID is not known before the first provider response. CodeCanopy therefore claims a frozen provider selector plus observed actual-model evidence, not pre-dispatch exact-ID attestation.

## Configuration

Bundled defaults use selectors instead of versioned IDs:

```toml
[model_discovery]
mode = "automatic"
release_channel = "ga"
refresh = "run_start"
on_failure = "fail"

[models.lead]
model = "auto"
reasoning_effort = "high"
```

The same `model = "auto"` value applies to `expert`, `worker`, and `reviewer`. An explicit project or user model ID pins that role and bypasses automatic role resolution after normal identifier and provider validation. Host/admin policy and current user instructions retain higher precedence.

`release_channel`, `refresh`, and `on_failure` accept only the values shown above in this release. They make the safety behavior explicit without introducing speculative modes.

## Frozen catalog and receipts

The resolver returns:

- provider;
- source (`codex_app_server` or `claude_aliases`);
- source version when available;
- resolved role-to-model and role-to-effort mapping;
- canonical SHA-256 catalog hash.

Discovery occurs once before manifest creation. `run_tree` receives the catalog hash, stores it in run details, includes it in every provider request and proof receipt, and rejects a resume whose catalog hash differs. Existing per-node requested model and effort checks continue to reject changed execution settings.

A model release affects only the next new run. A resumed run must use the original catalog or fail closed.

## Security and failure behavior

- JSON-RPC input and output are bounded by existing provider limits and a ten-second discovery timeout.
- The catalog is parsed as untrusted structured data with exact type, count, identifier, and reasoning-effort validation.
- Discovery runs only in the root process. Child prompts receive only their selected model and bounded node contract.
- Authentication stays inside the provider CLI. No key, token, raw catalog, prompt, or output is persisted.
- Missing executable, malformed response, ambiguous default, unsupported effort, or incomplete role coverage fails before node dispatch.
- An explicit pinned model remains available for controlled rollouts, but it is never an automatic fallback.

## Acceptance checks

1. A synthetic future Codex catalog makes the resolver choose the new default, balanced, and economical entries without changing CodeCanopy source or configuration.
2. Hidden, specialty, superseded, unavailable, malformed, and incomplete catalogs fail closed.
3. Claude automatic roles produce `best`, `sonnet`, and `haiku`; explicit model pins remain exact.
4. Claude commands include model and supported effort before the prompt, and receipts extract one observed actual model without storing provider output.
5. A catalog hash is immutable across a run and a mismatched resume is rejected before provider execution.
6. Existing provider isolation, manifest, routing, benchmark, and workflow tests remain green.

## Evidence boundary

Passing deterministic tests proves selection-policy conformance and fail-closed behavior. It does not prove comparative model quality, global public availability, token savings, latency improvement, or provider equivalence.
