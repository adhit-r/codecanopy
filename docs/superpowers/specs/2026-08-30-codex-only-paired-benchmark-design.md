# Codex-Only Paired Benchmark Design

## Status

Approved in chat on 2026-08-30 for specification. Implementation remains gated on review of this document.

## Goal

Produce reproducible, receipt-backed evidence comparing one sequential Codex lead with CodeCanopy's current fixed-plan, model-routed Codex graph for token use, wall time, and deterministic review quality.

## Product truth

The v0.4 runtime executes topologically ordered nodes serially. Its routing fixture selects configured model tiers, but `ProviderRequest` does not yet pass a selected model to Codex. The first paired benchmark therefore measures sequential graph orchestration with explicit model routing. It does not measure parallel execution, code-writing integration, or a globally shortest path.

The installed Codex CLI is version 0.147.0. `codex exec --json` promises JSONL output, but its help does not promise token-usage or actual-model fields. One bounded schema probe must establish the available evidence before the runner accepts live measurements.

## Scope

Version `codex-readonly-v1` includes:

- Codex CLI only, with no provider fallback;
- three immutable read-only engineering-review cases: small, medium, and complex;
- one sequential lead arm and one fixed-plan CodeCanopy arm;
- three randomized repetitions per case, for eighteen total arm executions;
- provider-reported token usage and actual-model identity only when the observed CLI schema supplies them;
- monotonic wall time, deterministic quality scoring, node count, and critical-path count;
- append-only, owner-only summary records containing hashes and metrics but no prompts, transcripts, raw model output, credentials, or raw JSONL events;
- a publication gate that refuses comparative deltas from incomplete pairs.

## Non-goals

This slice does not add a parallel scheduler, writing agents, Git integration, Claude support, mixed-provider execution, benchmark CI, a hosted results service, statistical significance claims, or a general benchmark framework.

## Alternatives considered

### Selected: fixed-plan, read-only paired runner

Use a small standard-library runner around the existing provider boundary. It can measure current behavior without adding a scheduler or integration engine. Deterministic findings make quality independently checkable.

### Deferred: full code-writing benchmark

Writing tasks require branch ownership, dependency commit materialization, root integration, conflict accounting, and equivalent post-integration acceptance. Building these before the first measurement would combine benchmark work with a new execution subsystem.

### Rejected: manual command capture

Manual runs do not reliably preserve order randomization, immutable baselines, incomplete runs, schema validation, or leak-safe result records.

## Architecture

### 1. Codex evidence probe

`benchmarks/paired_codex.py probe --execute` runs exactly one read-only, ephemeral Codex invocation with the lead model and the prompt `Return exactly OK.` in a temporary Git repository. Without `--execute`, the command prints the intended provider, requested model, reasoning effort, sandbox, timeout, and working-directory policy, then exits without invoking Codex. Model-tool and workspace network access remain disabled; the user-approved Codex service connection remains necessary. Approvals remain disabled, user configuration and repository rules remain ignored, and the timeout is 120 seconds.

The probe parses JSONL in memory and reports only event type names, discovered usage-key names, requested model, requested reasoning effort, discovered actual model, aggregate token counts, final-response location, exit status, and a SHA-256 hash of the bounded output. It never writes the raw events or final response. An allowlisted redacted fixture derived from the observed shape becomes the parser test fixture.

Implementation freezes one schema adapter only after the probe: exact CLI version `0.147.0`, exact top-level event types, exact nested JSON paths for terminal usage, actual model, and final response, plus a SHA-256 fingerprint of that canonical adapter specification. Live runs require the same CLI version and adapter fingerprint. Token values must be non-negative integers no larger than `2^63 - 1`. The parser accepts exactly one terminal usage summary and treats it as cumulative for the invocation; it never sums repeated progress events. Missing or duplicate terminal summaries, unknown event types at trusted telemetry paths, changed types, and unknown final-response shapes make the invocation incomplete. Model-authored JSON inside response content is never interpreted as CLI telemetry.

If the CLI output does not contain provider-reported input and output tokens plus actual-model identity, the probe succeeds as a capability check but records those fields as unavailable. Live paired runs may still record wall time and quality, but token deltas and publishable comparative charts remain unavailable.

### 2. Trusted model selection

`ProviderRequest` gains optional `model` and `reasoning_effort` fields. They are supplied by trusted Python callers only; plan JSON remains unable to select either value. For Codex, the command builder inserts `--model <model>` and the validated `model_reasoning_effort` configuration before the dispatched prompt. Model values must be non-empty bounded identifiers containing only letters, numbers, `.`, `_`, `-`, and `:`. Reasoning effort must be exactly `low`, `medium`, `high`, `xhigh`, `max`, or `ultra`. Supplying either setting for Claude fails before execution; existing Claude calls that omit them remain unchanged.

Provider results and proof receipts record `requested_model` and `requested_reasoning_effort`. The benchmark result receipt records `actual_model` only when the benchmark parser observes it in an allowlisted Codex event; it is never inferred from the requested value. Existing callers that omit both fields retain current behavior.

### 3. Case corpus

The repository stores three synthetic source corpora under `benchmarks/cases/codex-readonly-v1/`. Each case has a `subject/` directory, a public `task.txt`, benchmark-owned `dag.json`, and a private-to-the-harness `oracle.json`. A checked-in copy manifest lists only `task.txt` and paths below `subject/`. Excluding `.git`, the temporary provider working tree must contain exactly that manifest, and `git ls-files` must return the same set. Tests reject `dag.json`, `oracle.json`, scorer code, result files, and other repository files; generated Git objects and the index can therefore reference only manifest-listed content.

The runner creates a fresh temporary Git repository for each arm, copies only the subject files, and creates a deterministic baseline commit using fixed author, committer, timestamp, and message values. Both arms in a pair must resolve to the same tree and baseline commit before execution.

Before scheduling, the harness computes one canonical case-definition hash from a versioned canonical JSON object containing the SHA-256 digest of `task.txt`, the copy manifest, `dag.json`, and `oracle.json`. The canonical object uses sorted keys, compact separators, and UTF-8 bytes; no filesystem path or metadata enters the digest. The hash is recorded for every arm and must remain identical within every pair and across all repetitions of that case. Any case file change therefore creates a distinct benchmark definition even though the private DAG and oracle never enter the provider-visible repository.

Each expected finding declares a canonical POSIX-relative file path, positive inclusive line interval, category, severity, and private description. Paths must be normalized, must not be absolute, and must contain neither `..` nor backslashes. Categories are exactly `correctness`, `security`, `reliability`, or `maintainability`; severities are exactly `low`, `medium`, `high`, or `critical`.

The model returns JSON findings with file, start line, end line, category, severity, and summary. Invalid fields make the invocation incomplete. A match requires identical canonical file, category, and severity plus intersecting line intervals. Ground truth forbids overlapping intervals for one file/category/severity tuple. Expected findings are processed in canonical field order; each selects the unmatched eligible prediction with the smallest absolute start-line distance, breaking ties by prediction order. Each expected and predicted finding may match at most once, so duplicate predictions remain false positives. Every case contains at least one expected finding. When no prediction is returned, precision, recall, and F1 are `0.0`; otherwise ordinary TP/FP/FN formulas apply, and F1 is `0.0` when precision plus recall is zero. A run is accepted only when precision and recall are each at least `0.80` and every expected `high` or `critical` finding is matched. A pair uses the same ground truth and scorer version.

### 4. Arms

The sequential arm sends the complete case to one invocation using the lead model and reasoning effort from the recorded CodeCanopy config snapshot; the current asset resolves this to `gpt-5.6-sol` with `high` effort.

The CodeCanopy arm uses the checked-in `dag.json` for the same case. Every node declares a role, complexity score, size score, and disjoint subject-file scope. The harness imports `load_config()`, `route_node()`, `NodeSignal`, and `RoutingDecision` from `model_routing.py` and loads only the checked-in CodeCanopy TOML asset. `RoutingConfig` and `RoutingDecision` are extended to retain and validate each tier's reasoning effort as well as its model. The harness records the asset's SHA-256 hash. The DAG cannot name a model, reasoning effort, or provider. The sequential lead uses the same config snapshot's lead model and effort.

`run_tree()` gains one optional trusted-Python callback with the exact interface `execution_settings(node: TreeNode) -> tuple[str | None, str | None]` and one optional trusted `execution_policy_hash: str | None` argument. The returned pair is requested model and reasoning effort; it cannot alter prompt, provider, timeout, fallback, working directory, or write access. The policy hash must be a lowercase 64-character SHA-256 hex digest when present. Neither input is exposed through plan JSON or the CLI. When absent, existing behavior is unchanged. The benchmark supplies a lookup keyed by node ID from the routing decisions and passes the recorded routing-config hash as the execution-policy hash.

`run_tree()` resolves the callback once per node before recording or validating its contract. It persists requested model, reasoning effort, and execution-policy hash in the node manifest; includes all three in `_verify_saved_contract()`; and then places the same model and effort values in `ProviderRequest`. A resumed run with a changed routing-config hash or callback output is rejected before dispatch and must use a new run ID, even when the changed config resolves to the same per-node settings. Tests prove the selected settings reach the intended node without mapping by prompt text and that recovery fails closed on either setting or policy-hash mismatch.

The current `run_tree()` dependency contract does not move child output into dependent prompts, so v1 aggregation is benchmark-local. The harness runs scoped leaf nodes through `run_tree()` and uses its acceptance callback to parse each final response into the strict findings schema. Each leaf's canonical findings artifact is capped at 8,000 characters and discarded after hashing. The combined artifact is capped at 24,000 characters. Before the reviewer invocation, the harness verifies that security preamble, reviewer instructions, delimiters, and aggregate together do not exceed `MAX_PROMPT_CHARS`; oversize input makes the arm incomplete before execution. Raw leaf JSONL, prose, and malformed findings never enter the reviewer prompt.

The bounded aggregate is serialized as canonical JSON, wrapped in an explicit untrusted-artifact delimiter and instruction, and passed directly to one reviewer selected by the routing policy's reviewer role. The reviewer returns the same strict findings schema. The runner includes every leaf and reviewer invocation in canopy token and wall-time totals. Tests cover the exact aggregate-plus-wrapper character boundary.

The v1 CodeCanopy arm runs nodes in current topological order, not concurrently. Its wall time is the complete sequential arm duration. The output and website must label it `sequential fixed-plan CodeCanopy v0.4`.

### 5. Run order and failure retention

`paired_codex.py run` requires an explicit `--execute` flag, a trusted result path, and an integer seed. It creates the eighteen-run schedule by randomizing arm order within each case and repetition. The schedule and seed are written before the first provider call.

Timeouts, non-zero exits, malformed output, output-cap termination, missing evidence, model mismatch, and failed quality parsing remain in the result set. The runner never retries automatically. A failed arm makes its pair incomplete.

### 6. Result records

The result file uses a benchmark-local `append_result_record()` built on the existing private-file boundary. It takes a Unix exclusive lock, checks the existing byte size before scanning, limits the ledger to 4 MiB, 1,000 non-empty events, and 64 KiB per serialized event, appends one canonical JSON line, flushes, and calls `fsync`. Tests cover symlink and hard-link refusal, pre-existing oversize rejection, event limits, durable successful appends, and preservation of the original ledger when validation fails before append. It does not claim crash-atomic recovery from a torn filesystem write. Every record contains:

- benchmark and scorer versions;
- case, repetition, arm, seed, and schedule position;
- immutable baseline and subject-tree hash;
- canonical case-definition hash binding the task, copy manifest, DAG, and oracle;
- Codex CLI version and telemetry-adapter fingerprint;
- routing-config hash;
- requested and actual model plus requested reasoning effort per invocation;
- provider status, relative proof-receipt reference, and bounded-output hash per invocation;
- input, cached-input, reasoning-output, output, and total tokens when available;
- wall seconds from a monotonic clock;
- quality counts, precision, recall, F1, and acceptance verdict;
- planned, executed, failed, and pruned node counts;
- critical-path node count;
- completion state and exact incomplete reasons.

It never contains the task prompt, security preamble, raw JSONL, final response, leaf output, reviewer input, credentials, environment values, or repository paths outside opaque case identifiers.

Every provider invocation writes exactly one existing hash-only proof-receipt row to a fresh path below the trusted benchmark state directory. Its path includes the preassigned schedule position, case ID, arm, and node ID, so no repetition or node shares a receipt file. The result record uses a state-root-relative receipt reference and repeats the same output hash. The auditor rejects a result whose receipt is missing, contains other than one row, or has a different output hash. This is local integrity binding, not cryptographic authentication against an actor who can rewrite both files.

## Publication gate

A pair is publishable only when:

- both arms use the same immutable baseline, subject-tree hash, CLI version, scorer version, timeout, sandbox, and acceptance contract;
- both arms use the same canonical case-definition hash, and every repetition for one case uses that hash;
- both arms use the same telemetry-adapter fingerprint and routing-config hash;
- all invocations completed without output truncation;
- provider-reported usage and actual-model identity are present for every invocation;
- actual models equal the requested models;
- every requested reasoning effort equals the selected value in the recorded config snapshot;
- both outputs parse and receive a deterministic quality score.

The report includes every scheduled run. The fixed pilot is publishable only when all nine pairs are complete; it never selects a successful subset. Token and time deltas use the formulas already defined in `benchmarks/README.md`. Quality delta is the canopy F1 minus sequential F1, with pass rates shown alongside it. Any incomplete pair blocks the comparative chart and leaves the website at `Not measured`, while the local report still lists every run and incomplete reason.

## Safety boundaries

- Model-tool and workspace network access remain disabled; only the approved Codex service connection is allowed.
- The runner accepts no arbitrary command, executable, environment override, provider, or fallback.
- Model identifiers come from the trusted checked-in CodeCanopy configuration.
- Case repositories and outputs are temporary and read-only to the provider.
- Results use owner-only, symlink-safe, hard-link-safe, size-bounded append semantics.
- Raw provider events remain in bounded memory only and are discarded after hashing and parsing.
- The probe and live benchmark are never part of CI because they consume provider capacity.
- Repository content and provider output remain untrusted data and cannot expand scope or authority.

## Files and responsibilities

- `benchmarks/paired_codex.py`: execution-gated probe, schedule construction, benchmark-local DAG execution and aggregation, invocation observation, fail-closed evidence parsing, bounded result appends, scoring, records, and report calculation.
- `benchmarks/cases/codex-readonly-v1/`: three subject corpora, public task descriptions, fixed DAG metadata, and ground truth kept outside provider-visible subject directories.
- `runtime/providers.py`: optional trusted model and reasoning-effort selection plus requested-setting receipt fields.
- `runtime/tree.py`: trusted node-to-model/effort callback wiring that is unavailable to plan JSON and CLI inputs.
- `tests/test_paired_codex.py`: parser, schedule, scoring, privacy, incomplete-pair, and delta behavior using redacted fixtures.
- `tests/test_providers.py`: model validation, command construction, and receipt evidence behavior.
- `benchmarks/README.md`: exact commands, evidence limits, and interpretation.
- `README.md`, `docs/index.html`, and `docs/llms.txt`: updated only after complete live evidence exists; otherwise they continue to say `Not measured`.

## Test strategy

Implementation follows red-green-refactor. Tests use real local files and subprocess-free redacted JSONL fixtures; only the external Codex invocation is replaced at the runner boundary.

Required behaviors are:

- invalid model identifiers fail before execution;
- invalid reasoning-effort values fail before execution;
- Codex commands include the trusted requested model and effort while Claude commands do not change;
- routing config and decisions preserve the configured effort, and node-ID settings reach only their intended requests;
- manifests bind requested model, effort, and execution-policy hash; recovery rejects changed settings or a changed routing config with otherwise identical selected settings before dispatch;
- known probe fixtures yield exact hand-calculated usage and actual-model values;
- unknown or missing event fields produce explicit incomplete reasons;
- an unknown CLI version or final-response shape makes an invocation incomplete;
- duplicate terminal usage summaries, non-integer tokens, and telemetry-adapter fingerprint mismatches make an invocation incomplete;
- seeded schedules are deterministic and contain eighteen arm executions;
- scorer results match hand-calculated true/false-positive and false-negative counts;
- duplicate predictions cannot match one expected finding twice, and zero-prediction scores are exactly zero;
- copied provider repositories contain only the public task and manifest-listed subject files;
- baseline or actual-model mismatches prevent deltas;
- case-definition hash mismatches within a pair or across repetitions prevent deltas;
- failed and interrupted arms remain in output;
- serialized records contain no prompt, response, transcript, credential, or raw event text;
- the result ledger refuses linked files and every byte/event cap violation without modifying the existing ledger;
- every invocation result binds to an existing proof receipt with the same output hash;
- every invocation uses one fresh schedule-position-and-node-specific receipt path;
- reviewer input never exceeds `MAX_PROMPT_CHARS` after the security preamble and wrapper are included;
- complete pairs calculate exact token, time, and F1 deltas;
- the existing full unit suite, routing benchmark, skill validator, plugin validator, and diff check remain green.

## Rollout

1. Implement and test trusted model selection and evidence parsing.
2. Run the single approved schema probe and freeze a redacted fixture for CLI 0.147.0.
3. Implement and test the corpus, schedule builder, scorer, and report gate.
4. Run one small-case pair as a harness acceptance check.
5. Run the complete eighteen-execution pilot only if the small pair is complete and leak-free.
6. Independently audit records and recompute deltas.
7. Update public documentation and charts only when the publication gate passes.

## Acceptance criteria

The slice is complete when the runner and tests are merged, the live pilot has either produced gate-complete evidence or a precise unavailable reason, and public claims exactly match that evidence. A working harness does not by itself justify replacing `Not measured`.
