# Codex-Only Paired Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a receipt-backed Codex-only benchmark that compares one sequential lead with CodeCanopy's current serial, model-routed graph and publishes deltas only when all evidence gates pass.

**Architecture:** Extend the existing provider and tree contracts with trusted model settings, then add one standard-library benchmark module for telemetry parsing, immutable synthetic cases, deterministic scoring, scheduling, result records, and publication gating. The current runtime remains serial; the benchmark measures that truth and stops after the small acceptance pair when the CLI cannot prove actual model identity.

**Tech Stack:** Python 3 standard library, `unittest`, local Codex CLI 0.147.0, JSONL, TOML via `tomllib`, Git CLI, GitHub Pages static HTML/CSS.

**Spec:** `docs/superpowers/specs/2026-08-30-codex-only-paired-benchmark-design.md`

## Global Constraints

- Apply Ponytail at full intensity: reuse existing provider, manifest, safe-I/O, and tree boundaries; add no dependency or general benchmark framework.
- Codex CLI only for this slice; provider fallback is always false.
- The measured arm label is exactly `sequential fixed-plan CodeCanopy v0.4`; do not claim parallel speedup or a globally shortest path.
- Use three immutable cases (`small`, `medium`, `complex`) and three repetitions, yielding nine pairs and eighteen scheduled arms.
- Provider execution is read-only, ephemeral, approval-free, instruction-isolated, credential-allowlisted, output-bounded, and workspace-network-disabled; only the approved Codex service connection is allowed.
- Persist hashes, normalized metrics, and relative receipt references only. Never persist prompts, security preambles, raw JSONL, final responses, leaf artifacts, reviewer prompts, credentials, environment values, or unrelated repository paths.
- CLI telemetry adapter is fixed to `codex-cli 0.147.0`; token counts are integers in `0..2^63-1`, and exactly one cumulative `turn.completed.usage` object is accepted.
- The approved probe observed `input_tokens`, `cached_input_tokens`, `cache_write_input_tokens`, `output_tokens`, and `reasoning_output_tokens`, plus one `item.completed` agent message. It observed no actual-model field.
- Missing actual-model evidence makes an invocation incomplete. Requested model is never substituted for actual model.
- Leaf canonical JSON is capped at 8,000 characters, the combined leaf aggregate at 24,000 characters, and the fully wrapped reviewer prompt at `MAX_PROMPT_CHARS`.
- Result JSONL is owner-only and limited to 4 MiB, 1,000 non-empty events, and 64 KiB per event under one Unix exclusive lock.
- Comparative publication requires all nine pairs. A successful subset never produces public token, time, or quality charts.
- Because the approved CLI probe lacked actual-model identity, implement and test the full harness, run one small acceptance pair, record the precise incomplete reason, and do not spend provider capacity on the remaining sixteen arms unless a later reviewed adapter supplies actual-model evidence.

## File Map

- Modify `benchmarks/model_routing.py`: retain and validate per-tier model plus reasoning effort.
- Modify `runtime/providers.py`: trusted Codex model/effort request fields and receipt evidence.
- Modify `runtime/tree.py`: node-to-request settings and immutable execution-policy binding.
- Create `benchmarks/paired_codex.py`: probe summary, telemetry adapter, corpus loader, scorer, schedule, arm execution, ledger, audit, and report gate.
- Create `benchmarks/cases/codex-readonly-v1/`: three immutable public subjects with private DAG/oracle inputs.
- Create `tests/test_model_routing.py`: routing model/effort contract tests.
- Modify `tests/test_providers.py`: provider command, validation, and receipt tests.
- Modify `tests/test_tree.py`: trusted settings propagation and resume-binding tests.
- Create `tests/test_paired_codex.py`: all benchmark logic with fake provider execution and temporary repositories.
- Modify `benchmarks/README.md`: exact local commands, observed adapter capability, and interpretation limits.
- Leave `README.md`, `docs/index.html`, and `docs/llms.txt` at `Not measured` while actual-model evidence is unavailable.

---

### Task 1: Preserve Routing Model and Reasoning Effort

**Files:**
- Modify: `benchmarks/model_routing.py:15-101`
- Create: `tests/test_model_routing.py`

**Interfaces:**
- Consumes: checked-in `plugins/code-canopy/skills/code-canopy/assets/codecanopy.toml`.
- Produces: `ModelSettings(model: str, reasoning_effort: str)`, `RoutingConfig.models: dict[str, ModelSettings]`, and `RoutingDecision.reasoning_effort: str` for Tasks 3 and 8.

- [ ] **Step 1: Write failing routing tests**

```python
from pathlib import Path
import tempfile
import unittest

from benchmarks.model_routing import NodeSignal, load_config, route_node


ASSET = Path("plugins/code-canopy/skills/code-canopy/assets/codecanopy.toml")


class ModelRoutingTests(unittest.TestCase):
    def test_checked_in_asset_preserves_selected_effort(self):
        config = load_config(ASSET)
        decision = route_node(NodeSignal("small", "worker", 0.1, 0.1), config)
        self.assertEqual(("worker", "gpt-5.6-luna", "medium"), (
            decision.tier, decision.model, decision.reasoning_effort
        ))

    def test_each_override_retains_its_configured_effort(self):
        config = load_config(ASSET)
        cases = (
            (NodeSignal("security", "security", 0.1, 0.1), "lead", "high"),
            (NodeSignal("review", "reviewer", 0.1, 0.1), "reviewer", "high"),
            (NodeSignal("uncertain", "worker", None, None), "expert", "high"),
        )
        for node, tier, effort in cases:
            with self.subTest(node=node.name):
                decision = route_node(node, config)
                self.assertEqual((tier, effort), (decision.tier, decision.reasoning_effort))

    def test_invalid_or_missing_effort_is_rejected(self):
        text = ASSET.read_text(encoding="utf-8")
        invalid_configs = (
            text.replace('reasoning_effort = "medium"', 'reasoning_effort = "fast"'),
            text.replace('reasoning_effort = "medium"\n', ''),
        )
        for invalid in invalid_configs:
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "config.toml"
                path.write_text(invalid, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "reasoning effort"):
                    load_config(path)
```

- [ ] **Step 2: Run the tests and observe the contract failure**

Run: `python3 -m unittest tests.test_model_routing -v`

Expected: FAIL because `RoutingDecision` has no `reasoning_effort` and missing effort is currently accepted.

- [ ] **Step 3: Add the minimal settings type and validation**

```python
REASONING_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max", "ultra"})
REQUIRED_TIERS = frozenset({"worker", "expert", "lead", "reviewer"})


@dataclass(frozen=True)
class ModelSettings:
    model: str
    reasoning_effort: str


@dataclass(frozen=True)
class RoutingConfig:
    strategy: str
    complexity_weight: float
    size_weight: float
    worker_max_score: float
    expert_max_score: float
    models: dict[str, ModelSettings]


@dataclass(frozen=True)
class RoutingDecision:
    tier: str
    model: str
    reasoning_effort: str
    score: float | None
    reason: str
```

Replace the model-table load and decision return with:

```python
model_tables = data.get("models", {})
if not isinstance(model_tables, dict) or set(model_tables) != REQUIRED_TIERS:
    raise ValueError("models must define worker, expert, lead, and reviewer tiers")
models: dict[str, ModelSettings] = {}
for tier in sorted(REQUIRED_TIERS):
    table = model_tables[tier]
    model = table.get("model") if isinstance(table, dict) else None
    effort = table.get("reasoning_effort") if isinstance(table, dict) else None
    if not isinstance(model, str) or not model.strip():
        raise ValueError(f"{tier} model must be a non-empty string")
    if effort not in REASONING_EFFORTS:
        raise ValueError(f"{tier} reasoning effort must be one of {sorted(REASONING_EFFORTS)}")
    models[tier] = ModelSettings(model, effort)
```

```python
settings = config.models[tier]
return RoutingDecision(tier, settings.model, settings.reasoning_effort, score, reason)
```

Update the benchmark print line to include `effort={decision.reasoning_effort}`.

- [ ] **Step 4: Run routing tests and the existing fixture**

Run: `python3 -m unittest tests.test_model_routing -v && python3 benchmarks/model_routing.py`

Expected: tests PASS; routing remains 10/10 and invalid estimates remain 3/3.

- [ ] **Step 5: Commit the routing contract**

```bash
git add benchmarks/model_routing.py tests/test_model_routing.py
git commit -m "feat: preserve routing reasoning effort"
```

### Task 2: Pass Trusted Model Settings Through the Provider Boundary

**Files:**
- Modify: `runtime/providers.py:76-405`
- Modify: `tests/test_providers.py`

**Interfaces:**
- Consumes: trusted `model: str | None` and `reasoning_effort: str | None` values.
- Produces: validated `ProviderRequest` settings, exact Codex CLI arguments, and hash-only receipt fields used by Tasks 3, 4, and 8.

- [ ] **Step 1: Write failing command and validation tests**

```python
def test_codex_command_includes_trusted_model_and_effort_before_prompt(self) -> None:
    completed = subprocess.CompletedProcess([], 0, '{"type":"turn.completed","usage":{}}\n', "")
    with patch.object(providers, "_run_bounded", return_value=completed) as runner:
        providers.execute_provider(
            providers.ProviderRequest(
                "review",
                model="gpt-5.6-luna",
                reasoning_effort="medium",
            ),
            which=lambda _: "/bin/codex",
        )
    command = runner.call_args.args[0]
    self.assertEqual("/bin/codex", command[0])
    self.assertEqual("gpt-5.6-luna", command[command.index("--model") + 1])
    self.assertIn('model_reasoning_effort="medium"', command)
    self.assertEqual(providers.SECURITY_PREAMBLE + "review", command[-1])

def test_invalid_or_claude_model_settings_fail_before_execution(self) -> None:
    requests = (
        providers.ProviderRequest("review", model="../../escape"),
        providers.ProviderRequest("review", reasoning_effort="fast"),
        providers.ProviderRequest("review", preferred_provider="claude", model="claude"),
        providers.ProviderRequest("review", preferred_provider="claude", reasoning_effort="high"),
    )
    for request in requests:
        with self.subTest(request=request), patch.object(providers, "_run_bounded") as runner:
            with self.assertRaises(ValueError):
                providers.execute_provider(request, which=lambda _: "/bin/provider")
            runner.assert_not_called()
```

Extend the existing receipt test with:

```python
request = providers.ProviderRequest(
    "do work", model="gpt-5.6-luna", reasoning_effort="medium"
)
self.assertEqual("gpt-5.6-luna", row["requested_model"])
self.assertEqual("medium", row["requested_reasoning_effort"])
```

- [ ] **Step 2: Run provider tests and observe failure**

Run: `python3 -m unittest tests.test_providers -v`

Expected: FAIL because `ProviderRequest` rejects the new constructor fields.

- [ ] **Step 3: Implement bounded provider settings**

Add beside the existing limits:

```python
MODEL_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
REASONING_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max", "ultra"})
```

Add `import re`, then append fields to preserve positional callers:

```python
@dataclass(frozen=True)
class ProviderRequest:
    prompt: str
    preferred_provider: ProviderName = "codex"
    timeout_seconds: float = 300
    cwd: str | Path | None = None
    allow_fallback: bool = False
    write_access: bool = False
    model: str | None = None
    reasoning_effort: str | None = None
```

Add to `_validate_request()`:

```python
if request.model is not None and not MODEL_ID.fullmatch(request.model):
    raise ValueError("model must be a 1-128 character provider identifier")
if request.reasoning_effort is not None and request.reasoning_effort not in REASONING_EFFORTS:
    raise ValueError(f"reasoning_effort must be one of {sorted(REASONING_EFFORTS)}")
if request.preferred_provider == "claude" and (
    request.model is not None or request.reasoning_effort is not None
):
    raise ValueError("Claude requests cannot select model or reasoning effort")
```

Keep provider selection separate from the request so the existing explicitly authorized Claude-to-Codex fallback still builds the selected provider command:

```python
def _provider_command(
    provider: ProviderName,
    write_access: bool,
    *,
    model: str | None,
    reasoning_effort: str | None,
) -> tuple[str, ...]:
    command = list(DEFAULT_COMMANDS[provider])
    if write_access:
        mode = "workspace-write" if provider == "codex" else "acceptEdits"
        command[command.index("read-only" if provider == "codex" else "plan")] = mode
        if provider == "claude":
            command[command.index("Read,Grep,Glob")] = "Read,Edit,Write,Grep,Glob"
    if provider == "codex" and model is not None:
        command.extend(("--model", model))
    if provider == "codex" and reasoning_effort is not None:
        command.extend(("--config", f'model_reasoning_effort="{reasoning_effort}"'))
    return tuple(command)
```

Call it as `_provider_command(selected, request.write_access, model=request.model, reasoning_effort=request.reasoning_effort)` before appending the security-prefixed prompt. Add `requested_model` and `requested_reasoning_effort` to `_result().receipt_data` and `append_proof_receipt()`.

- [ ] **Step 4: Run provider tests**

Run: `python3 -m unittest tests.test_providers -v`

Expected: all provider tests PASS, including unchanged Claude calls with omitted settings.

- [ ] **Step 5: Commit the provider contract**

```bash
git add runtime/providers.py tests/test_providers.py
git commit -m "feat: add trusted Codex model selection"
```

### Task 3: Bind Node Settings and Routing Policy Into Recovery

**Files:**
- Modify: `runtime/tree.py:25-265`
- Modify: `tests/test_tree.py`

**Interfaces:**
- Consumes: `execution_settings(node: TreeNode) -> tuple[str | None, str | None]` and `execution_policy_hash: str | None`.
- Produces: cached per-node settings in `ProviderRequest` and immutable manifest details checked before redispatch.

- [ ] **Step 1: Write failing propagation and recovery tests**

```python
def test_trusted_settings_are_resolved_once_and_bound_to_each_node(self):
    calls = []
    resolutions = []
    policy_hash = "a" * 64

    def settings(node):
        resolutions.append(node.node_id)
        return {
            "one": ("gpt-5.6-luna", "medium"),
            "two": ("gpt-5.6-terra", "high"),
        }[node.node_id]

    def execute(request):
        calls.append((request.model, request.reasoning_effort))
        return ProviderResult("completed", "codex", "codex", False, 0, "ok", None, {})

    with tempfile.TemporaryDirectory() as directory:
        manifest = Path(directory) / "run.jsonl"
        run_tree(
            [TreeNode("one", "first"), TreeNode("two", "second")],
            manifest_path=manifest,
            run_id="settings",
            execution_settings=settings,
            execution_policy_hash=policy_hash,
            execute=execute,
        )
        snapshot = ManifestStore(manifest).snapshot("settings")

    self.assertEqual(["one", "two"], resolutions)
    self.assertEqual([("gpt-5.6-luna", "medium"), ("gpt-5.6-terra", "high")], calls)
    self.assertEqual(policy_hash, snapshot["nodes"]["one"]["details"]["execution_policy_hash"])

def test_changed_policy_hash_rejects_recovery_before_execution(self):
    with tempfile.TemporaryDirectory() as directory:
        manifest = Path(directory) / "run.jsonl"
        run_tree(
            [TreeNode("one", "first")],
            manifest_path=manifest,
            run_id="policy",
            execution_settings=lambda _node: ("gpt-5.6-luna", "medium"),
            execution_policy_hash="a" * 64,
            execute=lambda request: ProviderResult("completed", "codex", "codex", False, 0, "ok", None, {}),
        )
        with self.assertRaises(ManifestError):
            run_tree(
                [TreeNode("one", "first")],
                manifest_path=manifest,
                run_id="policy",
                execution_settings=lambda _node: ("gpt-5.6-luna", "medium"),
                execution_policy_hash="b" * 64,
                execute=lambda _request: self.fail("changed policy must not execute"),
            )
```

Add the same recovery test for a changed model and for a changed effort with the policy hash unchanged. Add a table-driven invalid hash test for uppercase, short, and non-hex values and assert the manifest path is not created.

- [ ] **Step 2: Run tree tests and observe failure**

Run: `python3 -m unittest tests.test_tree -v`

Expected: FAIL because `run_tree()` has no trusted settings arguments.

- [ ] **Step 3: Resolve and validate settings before any node contract write**

Add:

```python
_POLICY_HASH = re.compile(r"^[0-9a-f]{64}$")
ExecutionSettings = Callable[[TreeNode], tuple[str | None, str | None]]
```

Extend `run_tree()` with:

```python
execution_settings: ExecutionSettings | None = None,
execution_policy_hash: str | None = None,
```

Immediately after `_validate_run_id(run_id)`:

```python
if execution_policy_hash is not None and not _POLICY_HASH.fullmatch(execution_policy_hash):
    raise ValueError("execution_policy_hash must be a lowercase SHA-256 digest")
settings_by_node = {
    node.node_id: execution_settings(node) if execution_settings is not None else (None, None)
    for node in ordered
}
```

Pass the cached values into `store.record_node()` as `requested_model`, `requested_reasoning_effort`, and `execution_policy_hash`. Extend `_verify_saved_contract()` parameters and `expected` mapping with those exact values. Use the cached pair when constructing `ProviderRequest`; never call the callback again.

- [ ] **Step 4: Run tree and provider regression tests**

Run: `python3 -m unittest tests.test_tree tests.test_providers -v`

Expected: all tests PASS; untrusted plan JSON and CLI still expose no model, effort, or policy-hash input.

- [ ] **Step 5: Commit the recovery binding**

```bash
git add runtime/tree.py tests/test_tree.py
git commit -m "feat: bind routed settings to tree recovery"
```

### Task 4: Freeze the Observed Codex 0.147.0 Telemetry Adapter

**Files:**
- Create: `benchmarks/paired_codex.py`
- Create: `tests/test_paired_codex.py`

**Interfaces:**
- Consumes: bounded Codex stdout JSONL from `ProviderResult.output`.
- Produces: `TelemetryAdapter`, `InvocationObservation`, `parse_jsonl()`, `adapter_fingerprint()`, and a dry-run-by-default `probe` command for later benchmark tasks.

- [ ] **Step 1: Write failing parser and dry-run tests using redacted in-memory JSONL**

```python
import io
import json
from contextlib import redirect_stdout
import unittest

from benchmarks import paired_codex


OBSERVED_JSONL = "\n".join((
    json.dumps({"type": "thread.started", "thread_id": "redacted"}),
    json.dumps({"type": "turn.started"}),
    json.dumps({"type": "item.completed", "item": {
        "id": "redacted", "type": "agent_message", "text": "REDACTED"
    }}),
    json.dumps({"type": "turn.completed", "usage": {
        "input_tokens": 20,
        "cached_input_tokens": 4,
        "cache_write_input_tokens": 0,
        "output_tokens": 5,
        "reasoning_output_tokens": 1,
    }}),
))


class PairedCodexTests(unittest.TestCase):
    def test_observed_schema_parses_cumulative_usage_without_model_inference(self):
        result = paired_codex.parse_jsonl(OBSERVED_JSONL)
        self.assertEqual((20, 4, 0, 5, 1, 25), (
            result.input_tokens,
            result.cached_input_tokens,
            result.cache_write_input_tokens,
            result.output_tokens,
            result.reasoning_output_tokens,
            result.total_tokens,
        ))
        self.assertEqual("REDACTED", result.final_response)
        self.assertIsNone(result.actual_model)
        self.assertIn("actual_model_unavailable", result.incomplete_reasons)

    def test_duplicate_or_invalid_usage_is_incomplete(self):
        duplicate = OBSERVED_JSONL + "\n" + json.dumps({
            "type": "turn.completed",
            "usage": {"input_tokens": 1, "cached_input_tokens": 0,
                      "cache_write_input_tokens": 0, "output_tokens": 1,
                      "reasoning_output_tokens": 0},
        })
        self.assertIn("terminal_usage_count", paired_codex.parse_jsonl(duplicate).incomplete_reasons)
        invalid = OBSERVED_JSONL.replace('"input_tokens": 20', '"input_tokens": -1')
        self.assertIn("invalid_token_usage", paired_codex.parse_jsonl(invalid).incomplete_reasons)

    def test_unknown_top_level_event_type_is_incomplete(self):
        changed = OBSERVED_JSONL + "\n" + json.dumps({"type": "item.updated", "item": {}})
        self.assertIn("unknown_event_type", paired_codex.parse_jsonl(changed).incomplete_reasons)

    def test_model_authored_json_is_not_telemetry(self):
        forged = OBSERVED_JSONL.replace(
            '"text": "REDACTED"',
            '"text": "{\\"actual_model\\":\\"forged\\",\\"input_tokens\\":1}"',
        )
        result = paired_codex.parse_jsonl(forged)
        self.assertIsNone(result.actual_model)
        self.assertEqual(20, result.input_tokens)

    def test_unknown_cli_version_and_adapter_fingerprint_are_incomplete(self):
        observation = paired_codex.observe_invocation(
            OBSERVED_JSONL,
            cli_version="codex-cli 0.148.0",
            expected_adapter_fingerprint="0" * 64,
        )
        self.assertIn("cli_version_mismatch", observation.incomplete_reasons)
        self.assertIn("adapter_fingerprint_mismatch", observation.incomplete_reasons)

    def test_probe_without_execute_never_calls_provider(self):
        output = io.StringIO()
        with patch.object(paired_codex, "execute_provider") as execute, redirect_stdout(output):
            status = paired_codex.main(["probe"])
        self.assertEqual(0, status)
        self.assertIn('"execute": false', output.getvalue().lower())
        execute.assert_not_called()
```

- [ ] **Step 2: Run parser tests and observe the missing module**

Run: `python3 -m unittest tests.test_paired_codex -v`

Expected: FAIL because `benchmarks.paired_codex` does not exist.

- [ ] **Step 3: Add the fixed adapter and fail-closed parser**

Create these exact core types and adapter values:

```python
#!/usr/bin/env python3
"""Receipt-backed Codex-only paired benchmark; external execution is opt-in."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from typing import Mapping, Sequence


MAX_TOKEN_VALUE = 2**63 - 1
PROBE_PROMPT = "Return exactly OK."


@dataclass(frozen=True)
class TelemetryAdapter:
    cli_version: str
    observed_event_types: tuple[str, ...]
    terminal_event_type: str
    final_event_type: str
    final_item_type: str
    usage_fields: tuple[str, ...]
    actual_model_path: tuple[str, ...] | None


CODEX_0147 = TelemetryAdapter(
    cli_version="codex-cli 0.147.0",
    observed_event_types=("item.completed", "thread.started", "turn.completed", "turn.started"),
    terminal_event_type="turn.completed",
    final_event_type="item.completed",
    final_item_type="agent_message",
    usage_fields=(
        "input_tokens",
        "cached_input_tokens",
        "cache_write_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
    ),
    actual_model_path=None,
)


@dataclass(frozen=True)
class InvocationObservation:
    final_response: str | None
    input_tokens: int | None
    cached_input_tokens: int | None
    cache_write_input_tokens: int | None
    output_tokens: int | None
    reasoning_output_tokens: int | None
    total_tokens: int | None
    actual_model: str | None
    incomplete_reasons: tuple[str, ...]
```

Implement canonical fingerprinting and parsing with no recursive telemetry search:

```python
def adapter_fingerprint(adapter: TelemetryAdapter = CODEX_0147) -> str:
    payload = json.dumps(asdict(adapter), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(payload).hexdigest()


def parse_jsonl(output: str, adapter: TelemetryAdapter = CODEX_0147) -> InvocationObservation:
    reasons: list[str] = []
    events: list[Mapping[str, object]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            reasons.append("malformed_jsonl")
            continue
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            reasons.append("invalid_event_shape")
            continue
        events.append(event)

    protected = {"usage", "model", "actual_model"}
    for event in events:
        if event["type"] not in adapter.observed_event_types:
            reasons.append("unknown_event_type")
        allowed_usage = (
            event["type"] == adapter.terminal_event_type
            and set(event) == {"type", "usage"}
        )
        if protected.intersection(event) and not allowed_usage:
            reasons.append("unexpected_telemetry_shape")

    terminal = [event for event in events if event["type"] == adapter.terminal_event_type]
    usage: dict[str, int] | None = None
    if len(terminal) != 1:
        reasons.append("terminal_usage_count")
    else:
        candidate = terminal[0].get("usage")
        if not isinstance(candidate, dict) or set(candidate) != set(adapter.usage_fields):
            reasons.append("invalid_token_usage")
        elif any(
            isinstance(candidate[field], bool)
            or not isinstance(candidate[field], int)
            or not 0 <= candidate[field] <= MAX_TOKEN_VALUE
            for field in adapter.usage_fields
        ):
            reasons.append("invalid_token_usage")
        else:
            usage = {field: candidate[field] for field in adapter.usage_fields}

    messages = [
        event["item"]["text"]
        for event in events
        if event["type"] == adapter.final_event_type
        and isinstance(event.get("item"), dict)
        and event["item"].get("type") == adapter.final_item_type
        and isinstance(event["item"].get("text"), str)
    ]
    if len(messages) != 1:
        reasons.append("final_response_count")
    actual_model = None
    if adapter.actual_model_path is None:
        reasons.append("actual_model_unavailable")

    return InvocationObservation(
        final_response=messages[0] if len(messages) == 1 else None,
        input_tokens=usage["input_tokens"] if usage else None,
        cached_input_tokens=usage["cached_input_tokens"] if usage else None,
        cache_write_input_tokens=usage["cache_write_input_tokens"] if usage else None,
        output_tokens=usage["output_tokens"] if usage else None,
        reasoning_output_tokens=usage["reasoning_output_tokens"] if usage else None,
        total_tokens=(usage["input_tokens"] + usage["output_tokens"]) if usage else None,
        actual_model=actual_model,
        incomplete_reasons=tuple(dict.fromkeys(reasons)),
    )
```

`observe_invocation()` adds `cli_version_mismatch` unless the bounded `codex --version` result equals `CODEX_0147.cli_version`, and adds `adapter_fingerprint_mismatch` unless the caller's expected fingerprint equals `adapter_fingerprint(CODEX_0147)`. It then delegates to `parse_jsonl()` and merges reasons without duplicates.

- [ ] **Step 4: Add a dry-run probe command and record the already-observed capability**

`main(["probe"])` prints canonical JSON containing `execute: false`, provider `codex`, model `gpt-5.6-sol`, effort `high`, sandbox `read-only`, timeout `120`, the adapter fingerprint, and `actual_model_available: false`. `main(["probe", "--execute"])` is the only path that calls `execute_provider()`; it creates an empty temporary Git repository, verifies `provider_capability("codex", probe_version=True).version == CODEX_0147.cli_version`, executes `PROBE_PROMPT`, parses stdout in memory, prints only the allowlisted structural summary, and discards output.

The single approved live probe already ran on 2026-08-30. Its accepted structural evidence is:

```json
{
  "cli_version": "codex-cli 0.147.0",
  "event_types": ["item.completed", "thread.started", "turn.completed", "turn.started"],
  "usage_fields": ["cache_write_input_tokens", "cached_input_tokens", "input_tokens", "output_tokens", "reasoning_output_tokens"],
  "terminal_usage_path": ["turn.completed", "usage"],
  "final_response_path": ["item.completed", "item", "agent_message", "text"],
  "actual_model_path": null
}
```

Do not invoke the live probe a second time during implementation. Verify the dry-run only:

Run: `python3 benchmarks/paired_codex.py probe`

Expected: canonical JSON with `"execute": false` and `"actual_model_available": false`.

- [ ] **Step 5: Run focused tests and commit the adapter**

Run: `python3 -m unittest tests.test_paired_codex -v`

Expected: all parser and dry-run probe tests PASS.

```bash
git add benchmarks/paired_codex.py tests/test_paired_codex.py
git commit -m "feat: add fail-closed Codex telemetry adapter"
```

### Task 5: Add Immutable Synthetic Cases and Deterministic Baselines

**Files:**
- Modify: `benchmarks/paired_codex.py`
- Modify: `tests/test_paired_codex.py`
- Create: `benchmarks/cases/codex-readonly-v1/small/task.txt`
- Create: `benchmarks/cases/codex-readonly-v1/small/subject/percentage.py`
- Create: `benchmarks/cases/codex-readonly-v1/small/copy-manifest.json`
- Create: `benchmarks/cases/codex-readonly-v1/small/dag.json`
- Create: `benchmarks/cases/codex-readonly-v1/small/oracle.json`
- Create: equivalent five-file layouts under `medium/` and `complex/`.

**Interfaces:**
- Consumes: a trusted case-directory path below the fixed corpus root.
- Produces: `CaseDefinition`, `Finding`, `load_case_definition()`, `canonical_case_definition_hash()`, and `copy_case_repo()` for Tasks 6-9.

- [ ] **Step 1: Write failing corpus-isolation and hash tests**

```python
def test_case_hash_binds_manifest_dag_and_oracle(self):
    case = paired_codex.load_case_definition(paired_codex.CASE_ROOT / "small")
    original = paired_codex.canonical_case_definition_hash(case)
    with tempfile.TemporaryDirectory() as directory:
        copied = Path(directory) / "small"
        shutil.copytree(paired_codex.CASE_ROOT / "small", copied)
        oracle = copied / "oracle.json"
        oracle.write_text(oracle.read_text().replace('"medium"', '"high"'), encoding="utf-8")
        changed = paired_codex.canonical_case_definition_hash(
            paired_codex.load_case_definition(copied)
        )
    self.assertNotEqual(original, changed)

def test_provider_repository_contains_only_manifest_files(self):
    case = paired_codex.load_case_definition(paired_codex.CASE_ROOT / "medium")
    with tempfile.TemporaryDirectory() as directory:
        repo, baseline, tree_hash = paired_codex.copy_case_repo(case, Path(directory))
        tracked = subprocess.run(
            ["git", "-C", str(repo), "ls-files"], check=True, capture_output=True, text=True
        ).stdout.splitlines()
        visible = sorted(
            path.relative_to(repo).as_posix()
            for path in repo.rglob("*")
            if path.is_file() and ".git" not in path.parts
        )
    self.assertEqual(list(case.copy_manifest), sorted(tracked))
    self.assertEqual(list(case.copy_manifest), visible)
    self.assertNotIn("oracle.json", visible)
    self.assertNotIn("dag.json", visible)
    self.assertRegex(baseline, r"^[0-9a-f]{40,64}$")
    self.assertRegex(tree_hash, r"^[0-9a-f]{40,64}$")
```

Add invalid-path tests for absolute paths, `..`, backslashes, manifest duplicates, files outside `task.txt` and `subject/`, overlapping oracle intervals, unknown categories/severities, model/provider keys in the DAG, duplicate scopes, and missing files.

- [ ] **Step 2: Run the corpus tests and observe failure**

Run: `python3 -m unittest tests.test_paired_codex.PairedCodexTests.test_case_hash_binds_manifest_dag_and_oracle tests.test_paired_codex.PairedCodexTests.test_provider_repository_contains_only_manifest_files -v`

Expected: FAIL because the corpus and loaders do not exist.

- [ ] **Step 3: Create the exact synthetic subjects**

Small `subject/percentage.py`:

```python
def percentage(part: int, total: int) -> float:
    return part * 100 / total
```

Its oracle contains one `correctness` / `medium` finding on line 2 for an unhandled zero denominator. Its DAG contains one worker leaf with complexity `0.10`, size `0.10`, and scope `subject/percentage.py`.

Medium `subject/archive.py`:

```python
from pathlib import Path


def write_entry(root: Path, name: str, data: bytes) -> None:
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
```

Medium `subject/retry.py`:

```python
def run_with_retries(operation, retries: int):
    for _ in range(retries):
        try:
            return operation()
        except TimeoutError:
            pass
    raise RuntimeError("operation failed")
```

Its oracle contains a `security` / `high` path-traversal finding on `archive.py:5-7` and a `correctness` / `medium` zero-attempt finding on `retry.py:1-2`. Its DAG contains two disjoint worker leaves: archive complexity/size `0.55/0.35`, retry `0.25/0.25`.

Complex `subject/auth.py`:

```python
def can_access(headers: dict[str, str]) -> bool:
    token = headers.get("Authorization")
    if token is None:
        return True
    return token == "Bearer internal"
```

Complex `subject/export.py`:

```python
def export_user(connection, user_id: str):
    query = f"SELECT * FROM users WHERE id = {user_id}"
    return connection.execute(query).fetchall()
```

Complex `subject/jobs.py`:

```python
def finish_job(job, handler) -> None:
    try:
        handler(job)
    except Exception:
        pass
    job.status = "complete"
```

Its oracle contains `security` / `critical` default-allow on `auth.py:3-4`, `security` / `critical` SQL injection on `export.py:2`, and `reliability` / `high` swallowed failure followed by completion on `jobs.py:2-6`. Its DAG contains three disjoint leaves: role `security` at `0.85/0.35`, role `worker` at `0.55/0.30`, and role `worker` at `0.25/0.25`.

Use these exact copy manifests, in small/medium/complex order:

```json
{"paths":["task.txt","subject/percentage.py"]}
```

```json
{"paths":["task.txt","subject/archive.py","subject/retry.py"]}
```

```json
{"paths":["task.txt","subject/auth.py","subject/export.py","subject/jobs.py"]}
```

Every task file says: `Review only the listed subject files. Return every material defect under the supplied JSON findings contract.` Every DAG node has only `id`, `role`, `complexity_score`, `size_score`, and `scope`. Every oracle finding has only `file`, `start_line`, `end_line`, `category`, `severity`, and `description`.

Use these exact DAG documents, in small/medium/complex order:

```json
{"nodes":[{"complexity_score":0.1,"id":"percentage","role":"worker","scope":["subject/percentage.py"],"size_score":0.1}]}
```

```json
{"nodes":[{"complexity_score":0.55,"id":"archive","role":"worker","scope":["subject/archive.py"],"size_score":0.35},{"complexity_score":0.25,"id":"retry","role":"worker","scope":["subject/retry.py"],"size_score":0.25}]}
```

```json
{"nodes":[{"complexity_score":0.85,"id":"auth","role":"security","scope":["subject/auth.py"],"size_score":0.35},{"complexity_score":0.55,"id":"export","role":"worker","scope":["subject/export.py"],"size_score":0.3},{"complexity_score":0.25,"id":"jobs","role":"worker","scope":["subject/jobs.py"],"size_score":0.25}]}
```

Use these exact oracle documents:

```json
{"findings":[{"category":"correctness","description":"total can be zero, causing division by zero","end_line":2,"file":"subject/percentage.py","severity":"medium","start_line":2}]}
```

```json
{"findings":[{"category":"security","description":"untrusted entry names can escape the destination root","end_line":7,"file":"subject/archive.py","severity":"high","start_line":5},{"category":"correctness","description":"zero retries performs zero attempts instead of an initial attempt","end_line":2,"file":"subject/retry.py","severity":"medium","start_line":1}]}
```

```json
{"findings":[{"category":"security","description":"missing authorization defaults to allow","end_line":4,"file":"subject/auth.py","severity":"critical","start_line":3},{"category":"security","description":"user id is interpolated into SQL","end_line":2,"file":"subject/export.py","severity":"critical","start_line":2},{"category":"reliability","description":"handler failure is swallowed and the job is marked complete","end_line":6,"file":"subject/jobs.py","severity":"high","start_line":2}]}
```

- [ ] **Step 4: Implement strict loaders, canonical hash, and baseline copy**

Use frozen dataclasses for `Finding`, `DagNode`, and `CaseDefinition`. Normalize paths with `PurePosixPath`, reject absolute/parent/backslash paths, require exact key sets, and byte-bound every JSON/task/subject read with the existing `read_regular_limited()` helper.

```python
@dataclass(frozen=True)
class Finding:
    file: str
    start_line: int
    end_line: int
    category: str
    severity: str
    description: str


@dataclass(frozen=True)
class DagNode:
    node_id: str
    role: str
    complexity_score: float
    size_score: float
    scope: tuple[str, ...]


@dataclass(frozen=True)
class CaseDefinition:
    case_id: str
    root: Path
    task: str
    copy_manifest: tuple[str, ...]
    dag: tuple[DagNode, ...]
    oracle: tuple[Finding, ...]
```

Compute the case hash from bounded descriptor-pinned reads:

```python
def canonical_case_definition_hash(case: CaseDefinition) -> str:
    limits = {"task": 16_384, "copy_manifest": 65_536, "dag": 65_536, "oracle": 65_536}
    digests = {
        name: sha256(_read_exact_limited(path, limits[name])).hexdigest()
        for name, path in {
            "task": case.root / "task.txt",
            "copy_manifest": case.root / "copy-manifest.json",
            "dag": case.root / "dag.json",
            "oracle": case.root / "oracle.json",
        }.items()
    }
    payload = {"schema_version": 1, "digests": digests}
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
```

`_read_exact_limited(path, limit)` calls `read_regular_limited(path, limit)`, raises when the returned length exceeds `limit`, and returns the bytes otherwise. Oracle `description` and predicted `summary` both populate the in-memory `Finding.description`; only predicted input accepts the key `summary`.

`copy_case_repo()` copies only manifest paths, initializes Git, sets local fixed identity, and commits with `GIT_AUTHOR_DATE=2000-01-01T00:00:00Z`, `GIT_COMMITTER_DATE=2000-01-01T00:00:00Z`, and message `CodeCanopy benchmark baseline`. It returns repository path, `rev-parse HEAD`, and `rev-parse HEAD^{tree}`.

- [ ] **Step 5: Run all corpus tests and commit**

Run: `python3 -m unittest tests.test_paired_codex -v`

Expected: all telemetry and corpus tests PASS.

```bash
git add benchmarks/paired_codex.py benchmarks/cases/codex-readonly-v1 tests/test_paired_codex.py
git commit -m "feat: add immutable Codex benchmark corpus"
```

### Task 6: Implement Deterministic Finding Scoring

**Files:**
- Modify: `benchmarks/paired_codex.py`
- Modify: `tests/test_paired_codex.py`

**Interfaces:**
- Consumes: strict predicted and expected `Finding` tuples.
- Produces: `Score(tp, fp, fn, precision, recall, f1, accepted)` used by arm records and publication gating.

- [ ] **Step 1: Write failing hand-calculated scorer tests**

```python
def test_scorer_is_one_to_one_and_counts_duplicates_as_false_positives(self):
    expected = (
        paired_codex.Finding("subject/a.py", 10, 12, "security", "high", "expected"),
    )
    predicted = (
        paired_codex.Finding("subject/a.py", 10, 10, "security", "high", "first"),
        paired_codex.Finding("subject/a.py", 11, 11, "security", "high", "duplicate"),
    )
    score = paired_codex.score_findings(expected, predicted)
    self.assertEqual((1, 1, 0), (score.tp, score.fp, score.fn))
    self.assertEqual((0.5, 1.0, 2 / 3), (score.precision, score.recall, score.f1))
    self.assertFalse(score.accepted)

def test_zero_predictions_scores_exactly_zero(self):
    expected = (
        paired_codex.Finding("subject/a.py", 1, 1, "correctness", "medium", "expected"),
    )
    score = paired_codex.score_findings(expected, ())
    self.assertEqual((0, 0, 1, 0.0, 0.0, 0.0, False), (
        score.tp, score.fp, score.fn, score.precision, score.recall, score.f1, score.accepted
    ))

def test_unmatched_high_finding_blocks_acceptance(self):
    expected = (
        paired_codex.Finding("subject/a.py", 1, 1, "security", "high", "required"),
        paired_codex.Finding("subject/b.py", 1, 1, "correctness", "low", "minor"),
    )
    predicted = (
        paired_codex.Finding("subject/b.py", 1, 1, "correctness", "low", "found"),
    )
    self.assertFalse(paired_codex.score_findings(expected, predicted).accepted)
```

- [ ] **Step 2: Run scorer tests and observe failure**

Run: `python3 -m unittest tests.test_paired_codex -v`

Expected: FAIL because `Score` and `score_findings()` do not exist.

- [ ] **Step 3: Implement canonical greedy matching**

```python
@dataclass(frozen=True)
class Score:
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float
    accepted: bool


def score_findings(expected: Sequence[Finding], predicted: Sequence[Finding]) -> Score:
    unmatched = set(range(len(predicted)))
    matched_expected: set[int] = set()
    order = sorted(range(len(expected)), key=lambda index: (
        expected[index].file,
        expected[index].category,
        expected[index].severity,
        expected[index].start_line,
        expected[index].end_line,
    ))
    for expected_index in order:
        wanted = expected[expected_index]
        eligible = [
            index for index in unmatched
            if predicted[index].file == wanted.file
            and predicted[index].category == wanted.category
            and predicted[index].severity == wanted.severity
            and predicted[index].start_line <= wanted.end_line
            and wanted.start_line <= predicted[index].end_line
        ]
        if eligible:
            selected = min(eligible, key=lambda index: (
                abs(predicted[index].start_line - wanted.start_line), index
            ))
            unmatched.remove(selected)
            matched_expected.add(expected_index)
    tp = len(matched_expected)
    fp = len(predicted) - tp
    fn = len(expected) - tp
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    required = {
        index for index, finding in enumerate(expected)
        if finding.severity in {"high", "critical"}
    }
    accepted = precision >= 0.8 and recall >= 0.8 and required <= matched_expected
    return Score(tp, fp, fn, precision, recall, f1, accepted)
```

Parse model findings with the same exact-key, path, category, severity, positive-line, and output-size validation as oracle findings. Invalid model JSON makes the invocation incomplete rather than an empty prediction.

- [ ] **Step 4: Run paired benchmark tests and commit**

Run: `python3 -m unittest tests.test_paired_codex -v`

Expected: scorer, corpus, parser, and probe dry-run tests PASS.

```bash
git add benchmarks/paired_codex.py tests/test_paired_codex.py
git commit -m "feat: add deterministic benchmark scoring"
```

### Task 7: Add the Seeded Schedule, Private Ledger, and Receipt Auditor

**Files:**
- Modify: `benchmarks/paired_codex.py`
- Modify: `tests/test_paired_codex.py`

**Interfaces:**
- Consumes: benchmark seed, trusted result/state roots, provider proof receipt rows, and normalized arm records.
- Produces: `RunContract`, `CaseSnapshot`, `ScheduleEntry`, `BenchmarkSchedule`, `build_schedule()`, `append_result_record()`, and `audit_proof_receipt()` for Tasks 8-10.

- [ ] **Step 1: Write failing schedule and ledger tests**

```python
def test_seeded_schedule_has_nine_pairs_and_eighteen_unique_positions(self):
    contract = fake_run_contract()
    cases = fake_case_snapshots()
    first = paired_codex.build_schedule(41, contract, cases)
    second = paired_codex.build_schedule(41, contract, cases)
    self.assertEqual(first, second)
    self.assertEqual(18, len(first.entries))
    self.assertEqual(list(range(18)), [entry.position for entry in first.entries])
    pairs = {(entry.case_id, entry.repetition) for entry in first.entries}
    self.assertEqual(9, len(pairs))
    for pair in pairs:
        self.assertEqual(
            {"sequential", "canopy"},
            {entry.arm for entry in first.entries if (entry.case_id, entry.repetition) == pair},
        )

def test_result_limits_leave_existing_ledger_unchanged(self):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "results.jsonl"
        paired_codex.append_result_record(path, {"kind": "schedule", "entries": []})
        original = path.read_bytes()
        with patch.object(paired_codex, "MAX_RESULT_EVENTS", 1):
            with self.assertRaisesRegex(ValueError, "event limit"):
                paired_codex.append_result_record(path, {"kind": "arm-result"})
        self.assertEqual(original, path.read_bytes())

def test_receipt_auditor_requires_one_matching_output_hash(self):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        receipt = root / "receipts" / "000-small-sequential" / "lead.jsonl"
        receipt.parent.mkdir(parents=True)
        receipt.write_text(json.dumps({"output_hash": "a" * 64}) + "\n", encoding="utf-8")
        receipt.chmod(0o600)
        reference = receipt.relative_to(root).as_posix()
        paired_codex.audit_proof_receipt(root, reference, "a" * 64)
        with self.assertRaisesRegex(ValueError, "output hash"):
            paired_codex.audit_proof_receipt(root, reference, "b" * 64)
        receipt.write_text(receipt.read_text() * 2, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "exactly one"):
            paired_codex.audit_proof_receipt(root, reference, "a" * 64)
```

Add symlink, hard-link, pre-existing 4 MiB oversize, 64 KiB event, and 1,000-event tests. Every rejection asserts the original bytes remain unchanged.

- [ ] **Step 2: Run the new tests and observe failure**

Run: `python3 -m unittest tests.test_paired_codex -v`

Expected: FAIL because scheduling and result-record functions do not exist.

- [ ] **Step 3: Implement the deterministic schedule**

```python
from random import Random


@dataclass(frozen=True)
class RunContract:
    benchmark_version: str
    scorer_version: str
    cli_version: str
    adapter_fingerprint: str
    routing_config_hash: str
    timeout_seconds: float
    sandbox: str
    acceptance_contract_hash: str


@dataclass(frozen=True)
class CaseSnapshot:
    case_id: str
    baseline: str
    subject_tree_hash: str
    case_definition_hash: str


@dataclass(frozen=True)
class ScheduleEntry:
    position: int
    case_id: str
    repetition: int
    arm: str


@dataclass(frozen=True)
class BenchmarkSchedule:
    seed: int
    run_contract: RunContract
    cases: tuple[CaseSnapshot, ...]
    entries: tuple[ScheduleEntry, ...]


def build_schedule(
    seed: int,
    run_contract: RunContract,
    cases: Sequence[CaseSnapshot],
) -> BenchmarkSchedule:
    random = Random(seed)
    entries: list[ScheduleEntry] = []
    for case_id in ("small", "medium", "complex"):
        for repetition in range(1, 4):
            arms = ["sequential", "canopy"]
            random.shuffle(arms)
            for arm in arms:
                entries.append(ScheduleEntry(len(entries), case_id, repetition, arm))
    return BenchmarkSchedule(seed, run_contract, tuple(cases), tuple(entries))
```

Before scheduling, the runner reads the routing config once, probes the bounded CLI version once, computes the adapter and acceptance-contract fingerprints, and constructs one immutable `RunContract` plus one `CaseSnapshot` per case. The `run` command serializes the resulting `BenchmarkSchedule` as the first canonical `schedule` record before its first provider call. It refuses a non-empty results path unless it contains the exact same first schedule record and no completed publication run. `load_results()` uses `open_private(path, append=False)`, the ledger byte/event caps, exact-key validation, and typed dataclass construction; it requires exactly one first `schedule` row and rejects any later schedule row.

- [ ] **Step 4: Implement the bounded private ledger and receipt audit**

Reuse `open_private()` and the provider receipt pattern:

```python
MAX_RESULT_BYTES = 4 * 1024 * 1024
MAX_RESULT_EVENTS = 1_000
MAX_RESULT_EVENT_BYTES = 64 * 1024


def append_result_record(path: Path, record: Mapping[str, object]) -> None:
    serialized = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
    encoded_size = len(serialized.encode("utf-8"))
    if encoded_size > MAX_RESULT_EVENT_BYTES:
        raise ValueError("benchmark result event size limit exceeded")
    with open_private(path, append=True) as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            existing_size = os.fstat(handle.fileno()).st_size
            if existing_size > MAX_RESULT_BYTES:
                raise ValueError("benchmark result size limit exceeded")
            handle.seek(0)
            events = sum(1 for line in handle if line.strip())
            if events >= MAX_RESULT_EVENTS:
                raise ValueError("benchmark result event limit exceeded")
            if existing_size + encoded_size > MAX_RESULT_BYTES:
                raise ValueError("benchmark result size limit exceeded")
            handle.seek(0, os.SEEK_END)
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
```

`audit_proof_receipt(state_root, reference, output_hash)` rejects absolute/parent/backslash references, opens the file with `open_private(path, append=False)` so ownership, private mode, symlinks, special files, and hard links are rechecked, rejects `fstat()` sizes above `MAX_RECEIPT_EVENT_BYTES`, reads at most `MAX_RECEIPT_EVENT_BYTES + 1`, requires exactly one non-empty JSON object, and compares its exact `output_hash` string. A receipt path is constructed as `receipts/{position:03d}-{case_id}-{arm}/{node_id}.jsonl`, so every invocation owns one fresh file.

- [ ] **Step 5: Run benchmark tests and commit**

Run: `python3 -m unittest tests.test_paired_codex -v`

Expected: all schedule, ledger, receipt, scorer, corpus, and parser tests PASS.

```bash
git add benchmarks/paired_codex.py tests/test_paired_codex.py
git commit -m "feat: add benchmark evidence ledger"
```

### Task 8: Execute Sequential and CodeCanopy Arms Through Existing Boundaries

**Files:**
- Modify: `benchmarks/paired_codex.py`
- Modify: `tests/test_paired_codex.py`

**Interfaces:**
- Consumes: `CaseDefinition`, `ScheduleEntry`, one pre-dispatch `RoutingConfig`, one immutable `RunContract`, `execute_provider()`, `run_tree()`, parser, scorer, and receipt functions.
- Produces: normalized `ArmRecord` values with every invocation, score, node counts, wall time, hashes, and incomplete reasons.

- [ ] **Step 1: Write failing fake-execution tests for both arms**

```python
def completed_result(request, findings):
    final = json.dumps({"findings": findings}, separators=(",", ":"))
    output = "\n".join((
        json.dumps({"type": "thread.started", "thread_id": "redacted"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.completed", "item": {
            "id": "redacted", "type": "agent_message", "text": final
        }}),
        json.dumps({"type": "turn.completed", "usage": {
            "input_tokens": 100, "cached_input_tokens": 0,
            "cache_write_input_tokens": 0, "output_tokens": 20,
            "reasoning_output_tokens": 5,
        }}),
    ))
    return ProviderResult("completed", "codex", "codex", False, 0, output, None, {})

def test_sequential_arm_uses_lead_settings_and_records_missing_actual_model(self):
    requests = []
    case = paired_codex.load_case_definition(paired_codex.CASE_ROOT / "small")
    with tempfile.TemporaryDirectory() as directory:
        record = paired_codex.run_sequential_arm(
            case,
            paired_codex.ScheduleEntry(0, "small", 1, "sequential"),
            state_root=Path(directory),
            execute=lambda request: requests.append(request) or completed_result(request, [{
                "file": "subject/percentage.py", "start_line": 2, "end_line": 2,
                "category": "correctness", "severity": "medium", "summary": "zero denominator"
            }]),
        )
    self.assertEqual(("gpt-5.6-sol", "high"), (requests[0].model, requests[0].reasoning_effort))
    self.assertTrue(record.score.accepted)
    self.assertIn("actual_model_unavailable", record.incomplete_reasons)

def test_canopy_arm_routes_leaf_and_reviewer_without_raw_leaf_prompt_reuse(self):
    requests = []
    case = paired_codex.load_case_definition(paired_codex.CASE_ROOT / "small")
    finding = [{
        "file": "subject/percentage.py", "start_line": 2, "end_line": 2,
        "category": "correctness", "severity": "medium", "summary": "zero denominator"
    }]
    with tempfile.TemporaryDirectory() as directory:
        record = paired_codex.run_canopy_arm(
            case,
            paired_codex.ScheduleEntry(1, "small", 1, "canopy"),
            state_root=Path(directory),
            execute=lambda request: requests.append(request) or completed_result(request, finding),
        )
    self.assertEqual("gpt-5.6-luna", requests[0].model)
    self.assertEqual("gpt-5.6-terra", requests[-1].model)
    self.assertEqual(2, record.executed_nodes)
    self.assertTrue(record.score.accepted)
    self.assertNotIn("thread.started", requests[-1].prompt)
```

Add tests for malformed leaf output, failed provider status, output truncation, an injected `KeyboardInterrupt`, reviewer aggregate exactly at 24,000 characters, fully wrapped prompt exactly at `MAX_PROMPT_CHARS`, one-character overflow rejection before reviewer execution, fresh receipt references for every leaf/reviewer/lead invocation, and serialization that contains none of the raw prompt/final-response sentinel strings. The failed-leaf test must assert that `InvocationRecord.status == "failed"`, its receipt exists and audits, and the arm remains incomplete even though the acceptance callback was not invoked for that leaf.

- [ ] **Step 2: Run arm tests and observe failure**

Run: `python3 -m unittest tests.test_paired_codex -v`

Expected: FAIL because the arm runners do not exist.

- [ ] **Step 3: Implement one strict findings prompt and normalized observation path**

Define one `FINDINGS_INSTRUCTIONS` constant that names the exact JSON object shape `{findings: [...]}`, exact six finding fields, allowed categories/severities, assigned file scope, and untrusted-data boundary. Compose prompts only from the public task, assigned scope, and these instructions.

Add:

```python
@dataclass(frozen=True)
class InvocationRecord:
    node_id: str
    requested_provider: str
    provider: str | None
    fallback_used: bool
    exit_code: int | None
    requested_model: str
    requested_reasoning_effort: str
    actual_model: str | None
    status: str
    receipt: str
    output_hash: str
    input_tokens: int | None
    cached_input_tokens: int | None
    cache_write_input_tokens: int | None
    output_tokens: int | None
    reasoning_output_tokens: int | None
    total_tokens: int | None
    incomplete_reasons: tuple[str, ...]


@dataclass(frozen=True)
class ArmRecord:
    entry: ScheduleEntry
    seed: int
    benchmark_version: str
    scorer_version: str
    baseline: str
    subject_tree_hash: str
    case_definition_hash: str
    routing_config_hash: str
    cli_version: str
    adapter_fingerprint: str
    timeout_seconds: float
    sandbox: str
    acceptance_contract_hash: str
    wall_seconds: float
    invocations: tuple[InvocationRecord, ...]
    score: Score | None
    planned_nodes: int
    executed_nodes: int
    failed_nodes: int
    pruned_nodes: int
    critical_path_nodes: int
    completion_state: str
    incomplete_reasons: tuple[str, ...]
```

`_invoke_direct()` handles only the sequential lead and reviewer: it executes a request, measures `time.monotonic_ns()`, parses telemetry in memory, parses final findings, writes one provider proof receipt, verifies that receipt, constructs `InvocationRecord`, and then drops raw output/final text from references.

Leaf execution stays inside `run_tree()`, which already writes its proof receipt for every returned status and calls the acceptance callback only for completed results. The benchmark's fixed DAG leaves are independent and `run_tree()` executes its stable topological order serially, so wrap the injected executor with an iterator over that exact ordered node-ID tuple. Capture `(node_id, request, result, duration)` before returning each result, including failed/timed-out/unavailable results. Use the acceptance callback only to parse completed findings keyed by its supplied `TreeNode`; after `run_tree()` returns, construct every executed leaf `InvocationRecord` from the captured node-ID mapping and audit the already-written receipt. Never append a second leaf receipt and never identify a node by prompt text or output hash. Add an assertion that the captured node-ID sequence equals the executed prefix of the planned independent-leaf order.

- [ ] **Step 4: Implement the two arms with current serial truth**

Each arm first calls `copy_case_repo()` into its own temporary root and verifies the returned baseline and subject-tree hash against the pre-dispatch per-case snapshot. The command layer loads the checked-in routing config once before writing the schedule and passes that object plus the immutable `RunContract` into every arm; arm functions never reload config. `run_sequential_arm()` selects `config.models["lead"]`, sends the complete manifest-listed case once with `ProviderRequest.cwd` set to that manifest-only repository, and scores its strict final findings. It never uses the CodeCanopy checkout as provider cwd.

Immediately before each provider invocation, re-run the bounded `codex --version` capability check and compare it with `RunContract.cli_version`; a mismatch records `cli_version_changed_during_run` and skips dispatch. Every arm copies its version, adapter fingerprint, routing hash, scorer version, timeout, sandbox, and acceptance-contract hash only from `RunContract`.

`run_canopy_arm()`:

1. Converts each DAG node to `NodeSignal`, calls `route_node()`, and hashes the exact TOML bytes.
2. Builds independent `TreeNode` leaves with disjoint file prompts and immutable baseline.
3. Calls `run_tree()` once with `repo` set to that arm's manifest-only repository, `worktree_root=None`, `allow_provider_fallback=False`, the node-ID settings callback, routing-config hash as `execution_policy_hash`, a schedule-specific manifest, and schedule-specific receipt directory.
4. Uses the acceptance callback to retain only parsed canonical findings per leaf; each artifact is rejected above 8,000 characters and removed after canonical aggregation.
5. Wraps the aggregate under an explicit untrusted-artifact delimiter, checks the 24,000-character aggregate cap and complete `SECURITY_PREAMBLE + reviewer prompt` cap, then calls the routed reviewer directly in a fresh empty temporary Git repository so it can consume only the bounded aggregate.
6. Scores only the reviewer findings and totals every leaf/reviewer invocation. `critical_path_nodes` is the longest DAG leaf path plus the reviewer; execution stays serial.

Do not add a scheduler, thread pool, generic provider registry, or persisted artifact bus.

Every normalized timeout, failed exit, malformed response, or cap termination is appended as an incomplete arm record with its exact reason. The runner never retries. On `KeyboardInterrupt`, append an `interrupted` arm record for the active schedule entry, flush it, and then re-raise so the operator retains evidence without the schedule continuing.

- [ ] **Step 5: Run benchmark and runtime regressions, then commit**

Run: `python3 -m unittest tests.test_paired_codex tests.test_tree tests.test_providers -v`

Expected: all tests PASS, and every fake invocation remains read-only with fallback false.

```bash
git add benchmarks/paired_codex.py tests/test_paired_codex.py
git commit -m "feat: execute paired Codex benchmark arms"
```

### Task 9: Enforce Pair Fairness and the All-Nine Publication Gate

**Files:**
- Modify: `benchmarks/paired_codex.py`
- Modify: `tests/test_paired_codex.py`

**Interfaces:**
- Consumes: schedule plus persisted `ArmRecord` mappings.
- Produces: `PairDelta`, `BenchmarkReport`, `publication_gate()`, `calculate_report()`, and execution-gated `acceptance`, `run`, and `report` commands.

- [ ] **Step 1: Write failing fairness and delta tests**

```python
def test_all_nine_complete_pairs_are_required_for_publication(self):
    schedule, records, state_root = write_complete_records_and_receipts_for_test(seed=41)
    report = paired_codex.calculate_report(
        schedule, records, state_root=state_root
    )
    self.assertTrue(report.publishable)
    self.assertEqual(9, len(report.pairs))
    self.assertEqual(18, report.sample_count)
    missing = records[:-1]
    blocked = paired_codex.calculate_report(
        schedule, missing, state_root=state_root
    )
    self.assertFalse(blocked.publishable)
    self.assertIn("all_nine_pairs_required", blocked.incomplete_reasons)

def test_pair_mismatch_blocks_delta(self):
    schedule, records, state_root = write_complete_records_and_receipts_for_test(seed=41)
    changed = replace(records[0], case_definition_hash="f" * 64)
    report = paired_codex.calculate_report(
        schedule, (changed, *records[1:]), state_root=state_root
    )
    self.assertFalse(report.publishable)
    self.assertIn("case_definition_mismatch", report.incomplete_reasons)

def test_subject_change_between_repetitions_blocks_publication(self):
    schedule, complete, state_root = write_complete_records_and_receipts_for_test(seed=41)
    records = list(complete)
    changed_index = next(
        index for index, record in enumerate(records)
        if record.entry.case_id == "small" and record.entry.repetition == 2
    )
    records[changed_index] = replace(records[changed_index], subject_tree_hash="e" * 40)
    report = paired_codex.calculate_report(
        schedule, records, state_root=state_root
    )
    self.assertFalse(report.publishable)
    self.assertIn("subject_tree_changed_across_repetitions", report.incomplete_reasons)

def test_run_contract_change_between_repetitions_blocks_publication(self):
    schedule, complete, state_root = write_complete_records_and_receipts_for_test(seed=41)
    for field, value, reason in (
        ("routing_config_hash", "d" * 64, "run_contract_changed_across_repetitions"),
        ("cli_version", "codex-cli 0.148.0", "run_contract_changed_across_repetitions"),
        ("adapter_fingerprint", "c" * 64, "run_contract_changed_across_repetitions"),
        ("scorer_version", "codex-findings-v2", "run_contract_changed_across_repetitions"),
        ("timeout_seconds", 121.0, "run_contract_changed_across_repetitions"),
        ("sandbox", "workspace-write", "run_contract_changed_across_repetitions"),
        ("acceptance_contract_hash", "b" * 64, "run_contract_changed_across_repetitions"),
    ):
        with self.subTest(field=field):
            records = list(complete)
            index = next(
                i for i, record in enumerate(records)
                if record.entry.case_id == "medium" and record.entry.repetition == 3
            )
            records[index] = replace(records[index], **{field: value})
            report = paired_codex.calculate_report(
                schedule, records, state_root=state_root
            )
            self.assertFalse(report.publishable)
            self.assertIn(reason, report.incomplete_reasons)

def test_receipt_mutation_before_report_blocks_publication(self):
    schedule, records, state_root = write_complete_records_and_receipts_for_test(seed=41)
    receipt = next(state_root.glob("receipts/*/*.jsonl"))
    receipt.write_text(json.dumps({"output_hash": "f" * 64}) + "\n", encoding="utf-8")
    receipt.chmod(0o600)
    report = paired_codex.calculate_report(
        schedule, records, state_root=state_root
    )
    self.assertFalse(report.publishable)
    self.assertIn("receipt_audit_failed", report.incomplete_reasons)

def test_records_that_agree_with_each_other_but_not_schedule_contract_are_blocked(self):
    schedule, complete, state_root = write_complete_records_and_receipts_for_test(seed=41)
    records = tuple(replace(record, routing_config_hash="d" * 64) for record in complete)
    report = paired_codex.calculate_report(schedule, records, state_root=state_root)
    self.assertFalse(report.publishable)
    self.assertIn("schedule_contract_mismatch", report.incomplete_reasons)

def test_exact_delta_formulas(self):
    delta = paired_codex.calculate_pair_delta(
        sequential_tokens=100, canopy_tokens=75,
        sequential_seconds=10.0, canopy_seconds=12.0,
        sequential_f1=0.5, canopy_f1=0.9,
    )
    self.assertEqual((-25.0, 20.0, 0.4), (
        delta.token_delta_percent, delta.time_delta_percent, delta.quality_delta
    ))
```

The `write_complete_records_and_receipts_for_test()` factory returns `(BenchmarkSchedule, tuple[ArmRecord, ...], Path)` and lives only in `tests/test_paired_codex.py`; do not add it to production code.

Add mismatch cases for baseline, subject tree, case definition, scorer version, timeout, sandbox, adapter fingerprint, routing hash, requested/actual model, requested effort, malformed result, truncation, and incomplete score. Add zero-baseline token/time tests that block deltas instead of dividing by zero.

- [ ] **Step 2: Run report tests and observe failure**

Run: `python3 -m unittest tests.test_paired_codex -v`

Expected: FAIL because report and publication functions do not exist.

- [ ] **Step 3: Implement exact pair checks and deltas**

Add the exact report types:

```python
@dataclass(frozen=True)
class PairDelta:
    case_id: str
    repetition: int
    token_delta_percent: float
    time_delta_percent: float
    quality_delta: float
    sequential_accepted: bool
    canopy_accepted: bool


@dataclass(frozen=True)
class BenchmarkReport:
    pairs: tuple[PairDelta, ...]
    sample_count: int
    median_token_delta_percent: float | None
    median_time_delta_percent: float | None
    median_quality_delta: float | None
    sequential_pass_rate: float | None
    canopy_pass_rate: float | None
    publishable: bool
    incomplete_reasons: tuple[str, ...]
```

`publication_gate(schedule: BenchmarkSchedule, records: Sequence[ArmRecord], state_root: Path) -> tuple[str, ...]` first compares every arm with `schedule.run_contract` and the matching `schedule.cases` snapshot; agreement among arm records is insufficient. For each `(case_id, repetition)`, require exactly one sequential and one canopy record. Require equality for baseline, subject-tree hash, case-definition hash, and every `RunContract` field. Across all eighteen arms, require exactly one benchmark version, scorer version, CLI version, adapter fingerprint, routing-config hash, timeout, sandbox, and acceptance-contract hash, all equal to the schedule's pre-dispatch `RunContract`. Across all three repetitions of one case, require exactly one baseline, subject-tree hash, and case-definition hash, all equal to the schedule's per-case snapshot. Require every invocation to be completed, untruncated, and populated with provider usage plus actual model equal to requested model. Require requested effort to equal the recorded config selection.

`calculate_report(schedule: BenchmarkSchedule, records: Sequence[ArmRecord], *, state_root: Path)` calls `publication_gate()` and reopens every invocation receipt immediately before checking publishability. A missing, replaced, linked, permission-weakened, multi-row, or output-hash-mismatched receipt adds `receipt_audit_failed`; an earlier successful audit stored in the result record is never trusted as current evidence. The CLI `report` command obtains both schedule and records from `load_results(results_path)` rather than reconstructing a schedule from the seed.

Calculate only complete pairs:

```python
token_delta_percent = 100 * (canopy_tokens - sequential_tokens) / sequential_tokens
time_delta_percent = 100 * (canopy_seconds - sequential_seconds) / sequential_seconds
quality_delta = canopy_f1 - sequential_f1
```

Use `statistics.median()` over all nine pair deltas and report both arm pass rates. The report always contains all scheduled entries and every incomplete reason. `publishable` is true only when all nine pairs are complete.

- [ ] **Step 4: Add explicit CLI execution gates**

The parser exposes:

```text
paired_codex.py probe [--execute]
paired_codex.py acceptance --execute --results PATH --state-dir PATH --seed INTEGER
paired_codex.py run --execute --results PATH --state-dir PATH --seed INTEGER
paired_codex.py report --results PATH --state-dir PATH
```

Without `--execute`, `probe`, `acceptance`, and `run` print canonical execution intent and return without calling Codex. `acceptance` schedules only the first randomized small pair and labels its report non-publishable. `run` always writes the full eighteen-arm schedule before execution and refuses to start when the adapter has no actual-model path; this prevents sixteen known-unpublishable provider calls after the small acceptance result confirms the limitation.

- [ ] **Step 5: Run all benchmark tests and commit**

Run: `python3 -m unittest tests.test_paired_codex -v`

Expected: all report, arm, ledger, schedule, scorer, corpus, parser, and dry-run CLI tests PASS.

```bash
git add benchmarks/paired_codex.py tests/test_paired_codex.py
git commit -m "feat: gate paired benchmark publication"
```

### Task 10: Document, Run the Small Acceptance Pair, and Verify the Slice

**Files:**
- Modify: `benchmarks/README.md`
- Modify only if the all-nine gate later passes: `README.md`, `docs/index.html`, `docs/llms.txt`
- Runtime evidence only, never committed: trusted result and state paths supplied to `acceptance`.

**Interfaces:**
- Consumes: completed unit-tested benchmark CLI.
- Produces: one audited small-pair result or an exact provider-capability failure; no comparative public chart from incomplete evidence.

- [ ] **Step 1: Update benchmark documentation with exact commands and observed capability**

Add these commands and statements to `benchmarks/README.md`:

```sh
python3 benchmarks/paired_codex.py probe
python3 benchmarks/paired_codex.py acceptance --execute \
  --results .codecanopy/benchmarks/codex-readonly-v1-results.jsonl \
  --state-dir .codecanopy/benchmarks/codex-readonly-v1-state \
  --seed 41
python3 benchmarks/paired_codex.py report \
  --results .codecanopy/benchmarks/codex-readonly-v1-results.jsonl \
  --state-dir .codecanopy/benchmarks/codex-readonly-v1-state
```

State that the 2026-08-30 Codex CLI 0.147.0 probe exposed cumulative token usage but no actual-model identity; requested model is not treated as actual model. Therefore the full pilot and comparative chart are blocked, while local small-pair wall-time, token, and deterministic-quality observations remain incomplete evidence and must not be marketed as gains.

- [ ] **Step 2: Run the complete local verification suite before external execution**

Run:

```sh
python3 -m unittest discover -v
python3 benchmarks/model_routing.py
python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-creator/scripts/quick_validate.py" plugins/code-canopy/skills/code-canopy
python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/plugin-creator/scripts/validate_plugin.py" plugins/code-canopy
git diff --check
```

Expected: all unit tests PASS, routing remains 10/10 with 3/3 invalid inputs rejected, both validators PASS, and diff check is clean.

- [ ] **Step 3: Commit the local harness documentation**

```bash
git add benchmarks/README.md
git commit -m "docs: explain paired benchmark evidence gate"
```

- [ ] **Step 4: Run exactly one small acceptance pair**

From a clean working tree, run:

```sh
python3 benchmarks/paired_codex.py acceptance --execute \
  --results .codecanopy/benchmarks/codex-readonly-v1-results.jsonl \
  --state-dir .codecanopy/benchmarks/codex-readonly-v1-state \
  --seed 41
```

Expected: schedule plus both arm records remain in the private owner-only ledger; every provider invocation has one matching receipt; the report includes `actual_model_unavailable`; and the command does not claim publication readiness.

- [ ] **Step 5: Audit the result and stop the full pilot**

Run:

```sh
python3 benchmarks/paired_codex.py report \
  --results .codecanopy/benchmarks/codex-readonly-v1-results.jsonl \
  --state-dir .codecanopy/benchmarks/codex-readonly-v1-state
```

Expected: `publishable` is false, the complete small-pair raw metrics are visible locally, and the reason includes both `actual_model_unavailable` and `all_nine_pairs_required`. Do not run `paired_codex.py run --execute`; its preflight must refuse while the frozen adapter lacks an actual-model path.

- [ ] **Step 6: Verify public truth remains unchanged**

Run:

```sh
rg -n "Not measured|not measured" README.md docs/index.html docs/llms.txt
git status --short
```

Expected: public surfaces still state `Not measured`; no result ledger, receipt, prompt, response, raw JSONL, or `.codecanopy` path is staged.

- [ ] **Step 7: Final review checkpoint**

Review the complete branch diff for raw provider content, absolute local paths, weakened provider isolation, model inference, parallel claims, best-subset selection, and accidental public metrics. Re-run the verification commands from Step 2 after every review fix.
