"""Paired Claude CLI token measurement: baseline vs v0.5 canopy vs efficient canopy.

Arms, per case:
- ``baseline``: one lead agent with file tools reviews the whole scope.
- ``canopy_v05``: one full agent per DAG leaf at its routed tier, then a reviewer agent.
- ``canopy_efficient``: Token Gate first. Below the gate, one lean call at the
  highest routed tier; above it, lean leaves merged deterministically.

Provider-reported usage only. This is a measurement script, not the hardened
runtime path: it builds commands with the runtime's own command builder but
runs them with the caller's environment so local CLI authentication works.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.model_routing import NodeSignal, load_config, route_node  # noqa: E402
from benchmarks.paired_codex import (  # noqa: E402
    CASE_ROOT,
    FINDINGS_INSTRUCTIONS,
    _aggregate_leaf_artifacts,
    _canonical_findings,
    _prompt,
    _reviewer_prompt,
    load_case_definition,
    parse_model_findings,
    score_findings,
)
from runtime.efficiency import (  # noqa: E402
    SplitPolicy,
    inline_scope,
    merge_findings,
    scope_work_tokens,
    scopes_disjoint,
    split_decision,
)
from runtime.model_catalog import CLAUDE_ALIASES  # noqa: E402
from runtime.providers import SECURITY_PREAMBLE, _provider_command  # noqa: E402

CONFIG = Path(__file__).resolve().parents[1] / "plugins/code-canopy/skills/code-canopy/assets/codecanopy.toml"
_TIER_ORDER = ("worker", "expert", "reviewer", "lead")


def _call(claude: str, cwd: Path, prompt: str, tier: str, effort: str, *, lean: bool) -> dict[str, object]:
    command = _provider_command("claude", False, model=CLAUDE_ALIASES[tier], reasoning_effort=effort, lean=lean)
    completed = subprocess.run(
        (claude, *command[1:], SECURITY_PREAMBLE + prompt),
        cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=600,
    )
    payload = json.loads(completed.stdout)
    if payload.get("is_error"):
        raise RuntimeError(f"claude call failed: {payload.get('result')}")
    usage = payload["usage"]
    tokens = sum(int(usage.get(key) or 0) for key in (
        "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"
    ))
    return {
        "tier": tier,
        "lean": lean,
        "models": sorted(payload.get("modelUsage", {})),
        "tokens": tokens,
        "cost_usd": float(payload.get("total_cost_usd") or 0.0),
        "result": str(payload.get("result", "")),
    }


def _json_text(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start >= 0 and end > start else text


def _findings(text: str, case):
    return parse_model_findings(_json_text(text), case).findings


def _summary(arm: str, calls: list[dict[str, object]], findings, case, note: str = "") -> dict[str, object]:
    score = score_findings(case.oracle, findings) if findings is not None else None
    return {
        "case": case.case_id,
        "arm": arm,
        "calls": len(calls),
        "tokens": sum(int(call["tokens"]) for call in calls),
        "cost_usd": round(sum(float(call["cost_usd"]) for call in calls), 6),
        "recall": None if score is None else score.recall,
        "accepted": None if score is None else score.accepted,
        "models": sorted({model for call in calls for model in call["models"]}),
        "note": note,
    }


def run_case(claude: str, case_id: str, policy: SplitPolicy, arms: Sequence[str]) -> list[dict[str, object]]:
    case = load_case_definition(CASE_ROOT / case_id)
    config = load_config(CONFIG)
    scope = tuple(path for path in case.copy_manifest if path.startswith("subject/"))
    routes = {
        node.node_id: route_node(NodeSignal(node.node_id, node.role, node.complexity_score, node.size_score), config)
        for node in case.dag
    }
    lead = config.models["lead"].reasoning_effort
    reviewer = route_node(NodeSignal("reviewer", "reviewer", 0.0, 0.0, requires_review=True), config)
    rows = []
    with tempfile.TemporaryDirectory(prefix="canopy-tokens-") as directory:
        work = Path(directory)
        shutil.copytree(case.root / "subject", work / "subject")
        if "baseline" in arms:
            call = _call(claude, work, _prompt(case.task, scope), "lead", lead, lean=False)
            rows.append(_summary("baseline", [call], _findings(call["result"], case), case))
        if "canopy_v05" in arms:
            calls, artifacts = [], {}
            for node in case.dag:
                decision = routes[node.node_id]
                call = _call(claude, work, _prompt(case.task, node.scope), decision.tier, decision.reasoning_effort, lean=False)
                calls.append(call)
                findings = _findings(call["result"], case)
                if findings is not None:
                    artifacts[node.node_id] = _canonical_findings(findings)
            review = _call(
                claude, work, _reviewer_prompt(_aggregate_leaf_artifacts(artifacts), task=case.task, scope=scope),
                "reviewer", reviewer.reasoning_effort, lean=False,
            )
            calls.append(review)
            rows.append(_summary("canopy_v05", calls, _findings(review["result"], case), case))
        if "canopy_efficient" in arms:
            work_tokens = {node.node_id: scope_work_tokens(work, node.scope) for node in case.dag}
            gate = split_decision(work_tokens, policy)
            note = f"gate: {gate.reason} (work={gate.total_work_tokens}, overhead={policy.agent_overhead_tokens})"
            if not gate.split:
                tier = max((routes[node.node_id].tier for node in case.dag), key=_TIER_ORDER.index)
                effort = next(routes[n.node_id].reasoning_effort for n in case.dag if routes[n.node_id].tier == tier)
                prompt = _inline_prompt(case.task, scope, inline_scope(work, scope))
                call = _call(claude, work, prompt, tier, effort, lean=True)
                rows.append(_summary("canopy_efficient", [call], _findings(call["result"], case), case, note))
            else:
                if not scopes_disjoint({node.node_id: node.scope for node in case.dag}):
                    raise ValueError("overlapping scopes need a reviewer; not covered by this script")
                calls, artifacts = [], {}
                for node in case.dag:
                    decision = routes[node.node_id]
                    prompt = _inline_prompt(case.task, node.scope, inline_scope(work, node.scope))
                    call = _call(claude, work, prompt, decision.tier, decision.reasoning_effort, lean=True)
                    calls.append(call)
                    findings = _findings(call["result"], case)
                    if findings is not None:
                        artifacts[node.node_id] = _canonical_findings(findings)
                merged = merge_findings(artifacts) if len(artifacts) == len(case.dag) else ""
                rows.append(_summary("canopy_efficient", calls, _findings(merged, case) if merged else None, case, note))
    return rows


def _inline_prompt(task: str, scope: Sequence[str], content: str) -> str:
    return (
        f"Public review task:\n{task.strip()}\n\n"
        f"Assigned file scope: {json.dumps(list(scope), separators=(',', ':'))}\n"
        "The scoped files are provided below with line numbers; no tools are available.\n\n"
        f"{content}\n{FINDINGS_INSTRUCTIONS}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--claude", default=shutil.which("claude") or "claude")
    parser.add_argument("--cases", nargs="+", default=["small", "medium", "complex"])
    parser.add_argument("--arms", nargs="+", default=["baseline", "canopy_v05", "canopy_efficient"])
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--results", type=Path, help="append JSONL rows here")
    arguments = parser.parse_args(argv)
    # Measure the real fixed overhead of one lean call; the gate uses it.
    probe_dir = Path(tempfile.mkdtemp(prefix="canopy-probe-"))
    try:
        probe = _call(arguments.claude, probe_dir, "Return exactly OK.", "worker", "low", lean=True)
    finally:
        shutil.rmtree(probe_dir, ignore_errors=True)
    policy = SplitPolicy(agent_overhead_tokens=int(probe["tokens"]))
    print(json.dumps({"probe_lean_overhead_tokens": probe["tokens"]}))
    for repeat in range(arguments.repeats):
        for case_id in arguments.cases:
            for row in run_case(arguments.claude, case_id, policy, arguments.arms):
                row["repeat"] = repeat
                line = json.dumps(row, sort_keys=True)
                print(line, flush=True)
                if arguments.results:
                    with arguments.results.open("a", encoding="utf-8") as handle:
                        handle.write(line + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
