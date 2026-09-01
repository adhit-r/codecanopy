# CodeCanopy benchmark contract

Benchmarks in this directory must distinguish deterministic policy evidence from comparative execution evidence. Do not infer model quality, token savings, latency, throughput, or production behavior from a routing-policy fixture.

## Evidence available now

Run:

```sh
python3 benchmarks/model_routing.py
```

The checked-in fixture verifies 10 expected routing decisions and rejects 3 invalid score inputs. Its 10 assignments are two `worker`, three `expert`, four `lead`, and one `reviewer`; six cases therefore have non-lead assignments. This distribution describes the fixture only. The sub-millisecond Python loop timing is not a provider benchmark and must not be published as performance evidence.

## Paired execution benchmark

Any claim that CodeCanopy is faster, uses fewer tokens, or improves accepted-task quality requires paired execution runs:

Before an executable Codex schedule is persisted, the benchmark resolves the bundled automatic role selectors once and freezes the exact IDs, source metadata, and catalog hash into the schedule and proof receipts. A provider-free schedule with `auto` selectors is unresolved and cannot be persisted or executed.

| Arm | Contract |
|---|---|
| Baseline | One lead model executes the requirement sequentially. |
| CodeCanopy | The same requirement is planned as a bounded ownership tree and artifact DAG, routed by the checked-in policy, and accepted bottom-up. |

Hold the requirement, repository commit, tool permissions, acceptance checks, context ceiling, provider access, and time budget constant. Repeat small, medium, and complex tasks under Codex-only, Claude-only, and explicitly authorized mixed-provider modes. Randomize arm order where provider caching or load could bias a run. Failed and interrupted runs remain in the result set.

Record for every arm:

- benchmark version, task ID, run ID, immutable baseline, and acceptance-check version;
- requested and actual execution surface, provider, and model for every node;
- input tokens, output tokens, and root orchestration tokens, using provider-reported usage only;
- wall-clock start and finish, accepted verdict, check results, retries, conflicts, and invalidations;
- planned, dispatched, accepted, and pruned node counts;
- artifact edges, critical-path node count, and dispatch-wave count;
- receipt or immutable evidence references without prompts, transcripts, credentials, or secrets.

For each paired task, report the raw values and calculate:

```text
token_delta_percent = 100 * (canopy_total_tokens - baseline_total_tokens) / baseline_total_tokens
time_delta_percent  = 100 * (canopy_wall_seconds - baseline_wall_seconds) / baseline_wall_seconds
```

Compare quality through the same predeclared acceptance checks or blinded rubric. Report pass rates beside token and time deltas; a cheaper failed run is not an improvement. Report medians and the complete sample count, not only the best run.

### Codex CLI local harness

Print the frozen adapter/capability summary without execution:

```sh
python3 benchmarks/paired_codex.py probe
```

Only `python3 benchmarks/paired_codex.py probe --execute` performs a live capability probe. Run the owner-only small acceptance pair for the approved real execution, then inspect its local report:

```sh
python3 benchmarks/paired_codex.py acceptance --execute \
  --results .codecanopy/benchmarks/codex-readonly-v1-results.jsonl \
  --state-dir .codecanopy/benchmarks/codex-readonly-v1-state \
  --seed 41
python3 benchmarks/paired_codex.py report \
  --results .codecanopy/benchmarks/codex-readonly-v1-results.jsonl \
  --state-dir .codecanopy/benchmarks/codex-readonly-v1-state
```

The 2026-08-30 Codex CLI 0.147.0 live probe exposed cumulative token usage but no actual-model identity. A requested model is not treated as an actual model. The full pilot and comparative chart are therefore blocked. Local small-pair wall-time, token, and deterministic-quality observations are incomplete evidence and must not be marketed as gains.

Local reports label the graph arm `sequential fixed-plan CodeCanopy v0.4` and list the state and reasons for all 18 scheduled runs, including missing records. If any publication-gate reason exists, the report emits no pair deltas, medians, or pass rates; chart-ready aggregates exist only after one clean all-nine-pair run.

## Publication gate

Publish a comparative chart only when both arms have complete provider-reported usage, immutable baselines, identical acceptance criteria, and receipt-backed actual provider/model identities. Label synthetic scheduler fixtures as synthetic. Until paired results exist, state `not measured` for token, wall-clock, and quality deltas and describe CodeCanopy's graph as a control model, not a proven speedup or globally optimal shortest-path algorithm.
