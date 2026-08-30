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

## Publication gate

Publish a comparative chart only when both arms have complete provider-reported usage, immutable baselines, identical acceptance criteria, and receipt-backed actual provider/model identities. Label synthetic scheduler fixtures as synthetic. Until paired results exist, state `not measured` for token, wall-clock, and quality deltas and describe CodeCanopy's graph as a control model, not a proven speedup or globally optimal shortest-path algorithm.
