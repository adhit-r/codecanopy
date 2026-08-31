# GA-Aware Model Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve current provider-released, account-available role models at each new tree run without hard-coded version names or mid-run switching.

**Architecture:** Add one standard-library model-catalog module above the existing `execution_settings` freeze point. Codex uses authenticated app-server `model/list` metadata; Claude uses provider-maintained aliases and records the observed backing model from result evidence. The existing tree manifest and proof receipts bind a canonical catalog hash to the run.

**Tech Stack:** Python 3.11 standard library, `unittest`, TOML, JSON-RPC over subprocess stdio, existing JSONL manifest and receipt stores.

**Spec:** `docs/superpowers/specs/2026-08-31-ga-model-resolution-design.md`

## Global Constraints

- Apply Ponytail at full intensity: standard library only, no network service, no release database, and no model-name parsing.
- Automatic discovery runs once before manifest creation; a running or resumed tree never re-resolves models.
- Codex eligibility uses only structured `model/list` fields; Claude automatic selection uses only `best`, `sonnet`, and `haiku` aliases.
- Hidden, specialty, superseded, unavailable, malformed, ambiguous, or incomplete catalogs fail closed.
- Provider fallback and model downgrade remain disabled unless the user explicitly authorizes the exact transition.
- Persist only model identifiers, source metadata, canonical hashes, and observed actual-model evidence; never raw catalogs, credentials, prompts, or outputs.
- Deterministic tests prove policy conformance only, not global GA, quality, latency, or token savings.

---

### Task 1: Provider-neutral run-start model catalog

**Files:**
- Create: `runtime/model_catalog.py`
- Create: `tests/test_model_catalog.py`
- Modify: `runtime/providers.py:513-578`

**Interfaces:**
- Consumes: existing `ProviderName`, `MODEL_ID`, `REASONING_EFFORTS`, `_provider_environment`, and `_run_bounded` from `runtime.providers`.
- Produces: `RoleModel(model: str, reasoning_effort: str)`, `ResolvedCatalog(provider, source, source_version, roles, catalog_hash)`, `load_role_settings(path)`, and `resolve_model_catalog(provider, role_settings, *, which=..., runner=...)`.
- Produces: `_run_bounded(..., input_data: bytes | None = None)` so JSON-RPC input is written and closed before bounded output capture.

- [ ] **Step 1: Write failing catalog-selection tests**

Add table-driven tests whose synthetic Codex response contains version-neutral IDs such as `frontier-next`, `balanced-next`, and `economy-next`. Assert:

```python
catalog = resolve_model_catalog("codex", automatic_roles(), which=lambda _: "/bin/codex", runner=fake_runner)
self.assertEqual("frontier-next", catalog.roles["lead"].model)
self.assertEqual("balanced-next", catalog.roles["expert"].model)
self.assertEqual("balanced-next", catalog.roles["reviewer"].model)
self.assertEqual("economy-next", catalog.roles["worker"].model)
self.assertEqual(64, len(catalog.catalog_hash))
```

The synthetic entries must distinguish roles only with `isDefault`, `hidden`, `availabilityNux`, `modelSpecialty`, `upgrade`, list order, and `supportedReasoningEfforts`.

- [ ] **Step 2: Write failing safety and Claude tests**

Cover these independent breaks:

```python
with self.assertRaisesRegex(ModelCatalogError, "eligible lead"):
    resolve_model_catalog("codex", automatic_roles(), which=lambda _: "/bin/codex", runner=ambiguous_default_runner)

claude = resolve_model_catalog("claude", automatic_roles(), which=lambda _: "/bin/claude")
self.assertEqual({"lead": "best", "expert": "sonnet", "reviewer": "sonnet", "worker": "haiku"}, {
    role: value.model for role, value in claude.roles.items()
})
```

Also reject oversized/malformed JSON-RPC, hidden candidates, availability notices, specialties, upgrade targets, unsupported efforts, more than 100 entries, missing executable, and invalid config. Verify an explicit valid model ID stays pinned for that role.

- [ ] **Step 3: Run the new tests and verify RED**

Run: `python3 -m unittest tests.test_model_catalog -v`

Expected: import failure for `runtime.model_catalog` or missing resolver symbols, proving production behavior does not yet exist.

- [ ] **Step 4: Add bounded stdin support**

Change `_run_bounded` to accept optional bytes:

```python
def _run_bounded(command, *, cwd, env, timeout, input_data: bytes | None = None):
    if input_data is not None and len(input_data) > 64 * 1024:
        raise ValueError("provider input exceeds 65536 bytes")
```

When input is present, start the process with `stdin=subprocess.PIPE`, write the bounded bytes, close stdin, then retain the existing selector-based output cap, timeout, process-group termination, and stream cleanup.

- [ ] **Step 5: Implement the minimal catalog resolver**

Use frozen dataclasses and canonical JSON hashing. Send exactly three newline-delimited JSON-RPC messages to Codex app-server, find response IDs `1` and `2`, and validate the `model/list` result. Automatic Codex role predicates are:

```python
lead = unique(item for item in eligible if item.is_default)
expert = first(item for item in eligible if not item.is_default and "ultra" in item.efforts)
worker = first(item for item in eligible if not item.is_default and "max" in item.efforts and "ultra" not in item.efforts)
```

`reviewer` reuses `expert`. A role with `model != "auto"` retains that exact validated pin and configured effort. Claude automatic aliases are the literal role map from the spec. Emit only the resolved object as JSON from `python3 -m runtime.model_catalog --provider <provider> --config <path>`.

- [ ] **Step 6: Verify GREEN and regression scope**

Run:

```bash
python3 -m unittest tests.test_model_catalog tests.test_providers -v
python3 -m runtime.model_catalog --provider claude --config plugins/code-canopy/skills/code-canopy/assets/codecanopy.toml
```

Expected: all selected tests pass; CLI output is one JSON object with role mappings and a 64-character catalog hash.

- [ ] **Step 7: Commit Task 1**

```bash
git add runtime/model_catalog.py runtime/providers.py tests/test_model_catalog.py
git commit -m "feat: resolve current provider model catalog"
```

---

### Task 2: Bind catalog identity and actual model evidence to execution

**Files:**
- Modify: `runtime/providers.py:115-144,253-305,343-393,415-432`
- Modify: `runtime/tree.py:110-261,283-313`
- Modify: `tests/test_providers.py`
- Modify: `tests/test_tree.py`

**Interfaces:**
- Consumes: `ResolvedCatalog.catalog_hash` and its resolved model/effort mapping from Task 1.
- Produces: `ProviderRequest.model_catalog_hash: str | None`, `ProviderResult.actual_model: str | None`, and `run_tree(..., model_catalog_hash: str | None = None)`.

- [ ] **Step 1: Write failing Claude command and receipt tests**

Assert a Claude request with `model="sonnet"` and `reasoning_effort="high"` places `--model sonnet --effort high` before the security prompt. Give `_result` a Claude JSON result with one `modelUsage` key and assert:

```python
self.assertEqual("claude-sonnet-current", result.actual_model)
self.assertEqual("claude-sonnet-current", receipt["actual_model"])
self.assertEqual("a" * 64, receipt["model_catalog_hash"])
```

Malformed JSON or multiple model keys must yield `actual_model is None`, never inferred prose.

- [ ] **Step 2: Write the failing run-freeze test**

Create a run with catalog hash `"a" * 64`, then resume the same run with `"b" * 64`. Assert `ManifestError` is raised before the fake provider is called. Also assert the initial run details, node request, and proof receipt contain the original hash.

- [ ] **Step 3: Run focused tests and verify RED**

Run:

```bash
python3 -m unittest tests.test_providers.ProviderTests.test_claude_command_includes_selected_model_and_effort -v
python3 -m unittest tests.test_tree.TreeRuntimeTests.test_resume_rejects_changed_model_catalog -v
```

Expected: missing fields or unsupported Claude settings cause the new assertions to fail.

- [ ] **Step 4: Implement provider evidence changes**

Add the two optional dataclass fields without breaking existing positional construction. Validate catalog hashes with the existing lowercase SHA-256 pattern. Permit Claude models that match `MODEL_ID`; permit only `low`, `medium`, `high`, `xhigh`, or `max` Claude efforts. Add `--model` and `--effort` before the prompt. Parse only a top-level JSON object whose `modelUsage` is a mapping with exactly one valid model key.

- [ ] **Step 5: Implement tree freeze changes**

Validate `model_catalog_hash` before any manifest mutation. Store it in `create_run` details. On resume, require the stored value to equal the requested value. Pass it into every `ProviderRequest`; existing per-node model, effort, and policy checks remain unchanged.

- [ ] **Step 6: Verify GREEN**

Run:

```bash
python3 -m unittest tests.test_providers tests.test_tree -v
```

Expected: all provider and tree tests pass with no warnings or errors.

- [ ] **Step 7: Commit Task 2**

```bash
git add runtime/providers.py runtime/tree.py tests/test_providers.py tests/test_tree.py
git commit -m "feat: freeze model catalogs in execution receipts"
```

---

### Task 3: Ship automatic defaults and truthful plugin documentation

**Files:**
- Modify: `plugins/code-canopy/skills/code-canopy/assets/codecanopy.toml`
- Modify: `benchmarks/model_routing.py`
- Modify: `tests/test_model_routing.py`
- Modify: `plugins/code-canopy/skills/code-canopy/SKILL.md`
- Modify: `plugins/code-canopy/skills/code-canopy/references/runtime-contract.md`
- Modify: `plugins/code-canopy/skills/code-canopy/references/codex-adapter.md`
- Modify: `plugins/code-canopy/skills/code-canopy/references/claude-adapter.md`
- Modify: `plugins/code-canopy/.codex-plugin/plugin.json`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/index.html`

**Interfaces:**
- Consumes: Task 1 CLI and Task 2 receipt/freeze fields.
- Produces: v0.5.0 plugin defaults and operator instructions that contain no bundled versioned role IDs.

- [ ] **Step 1: Write failing configuration tests**

Update the checked-in asset expectation to assert every tier returns `model == "auto"` while preserving the configured effort. Add invalid `[model_discovery]` fixtures for any value other than:

```toml
mode = "automatic"
release_channel = "ga"
refresh = "run_start"
on_failure = "fail"
```

- [ ] **Step 2: Run routing tests and verify RED**

Run: `python3 -m unittest tests.test_model_routing -v`

Expected: the current versioned bundled models fail the new `auto` assertion.

- [ ] **Step 3: Replace bundled version pins and validate policy**

Add the exact `[model_discovery]` table above and set all four bundled model values to `"auto"`. Extend `load_config` with a frozen `ModelDiscoveryConfig` and exact-value validation. Keep weighted complexity/size routing unchanged; its deterministic decision reports the selector `auto`, while live resolution remains a separate pre-run step.

- [ ] **Step 4: Update plugin and public documentation**

Document this sequence without universal-GA or quality claims:

```text
score node -> choose role tier -> resolve provider catalog once -> freeze catalog hash -> dispatch exact Codex ID or Claude alias -> record observed model evidence
```

State that Codex exact IDs come from authenticated host metadata, Claude exact IDs are observed from `modelUsage`, previews are not intentionally selected, and a malformed/incomplete catalog blocks dispatch. Add a compact GitHub Pages section explaining that a future host default and lower-capability entries are selected on the next new run, never midway through a tree.

Bump the plugin manifest and changelog to `0.5.0`.

- [ ] **Step 5: Verify plugin, docs, and full repository**

Run:

```bash
python3 -m unittest discover -s tests -v
python3 benchmarks/model_routing.py
python3 /Users/adhi/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py plugins/code-canopy
python3 /Users/adhi/.codex/skills/.system/skill-creator/scripts/quick_validate.py plugins/code-canopy/skills/code-canopy
git diff --check
```

Expected: unit suite passes; routing reports 10/10 cases and 3/3 invalid estimates; both validators succeed; whitespace check is clean.

- [ ] **Step 6: Commit Task 3**

```bash
git add plugins/code-canopy benchmarks/model_routing.py tests/test_model_routing.py README.md CHANGELOG.md docs/index.html
git commit -m "docs: ship automatic GA-aware model defaults"
```
