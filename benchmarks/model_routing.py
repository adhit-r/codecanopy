#!/usr/bin/env python3
"""Benchmark CodeCanopy's deterministic complexity/size model routing contract."""

from __future__ import annotations

import argparse
from collections import Counter
import math
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path


REASONING_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max", "ultra"})
REQUIRED_TIERS = frozenset({"worker", "expert", "lead", "reviewer"})


@dataclass(frozen=True)
class ModelSettings:
    model: str
    reasoning_effort: str


@dataclass(frozen=True)
class ModelDiscoveryConfig:
    mode: str
    release_channel: str
    refresh: str
    on_failure: str


AUTOMATIC_MODEL_DISCOVERY = ModelDiscoveryConfig("automatic", "ga", "run_start", "fail")


@dataclass(frozen=True)
class RoutingConfig:
    strategy: str
    complexity_weight: float
    size_weight: float
    worker_max_score: float
    expert_max_score: float
    models: dict[str, ModelSettings]
    model_discovery: ModelDiscoveryConfig = AUTOMATIC_MODEL_DISCOVERY


@dataclass(frozen=True)
class NodeSignal:
    name: str
    role: str
    complexity_score: float | None
    size_score: float | None
    requires_lead: bool = False
    requires_review: bool = False


@dataclass(frozen=True)
class RoutingDecision:
    tier: str
    model: str
    reasoning_effort: str
    score: float | None
    reason: str


def load_config(path: Path) -> RoutingConfig:
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    routing = data.get("routing", {})
    model_tables = data.get("models", {})
    discovery = data.get("model_discovery")
    if not isinstance(discovery, dict) or set(discovery) != set(AUTOMATIC_MODEL_DISCOVERY.__dataclass_fields__):
        raise ValueError("model discovery must define automatic GA run-start failure policy")
    model_discovery = ModelDiscoveryConfig(**discovery)
    if model_discovery != AUTOMATIC_MODEL_DISCOVERY:
        raise ValueError("model discovery must define automatic GA run-start failure policy")
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
    config = RoutingConfig(
        strategy=str(routing.get("strategy", "weighted_complexity_size")),
        complexity_weight=float(routing.get("complexity_weight", 0.6)),
        size_weight=float(routing.get("size_weight", 0.4)),
        worker_max_score=float(routing.get("worker_max_score", 0.33)),
        expert_max_score=float(routing.get("expert_max_score", 0.66)),
        models=models,
        model_discovery=model_discovery,
    )
    if config.strategy != "weighted_complexity_size":
        raise ValueError("routing strategy must be weighted_complexity_size")
    if config.complexity_weight <= 0 or config.size_weight <= 0:
        raise ValueError("routing weights must be positive")
    if not 0 <= config.worker_max_score < config.expert_max_score <= 1:
        raise ValueError("routing thresholds must satisfy 0 <= worker < expert <= 1")
    return config


def _score(value: float | None, label: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{label} must be a finite number from 0 to 1")
    return float(value)


def route_node(node: NodeSignal, config: RoutingConfig) -> RoutingDecision:
    complexity = _score(node.complexity_score, "complexity_score")
    size = _score(node.size_score, "size_score")
    if node.requires_lead or node.role in {"root", "integration", "security"}:
        tier, reason = "lead", "safety or integration override"
        score = None if complexity is None or size is None else (
            config.complexity_weight * complexity + config.size_weight * size
        ) / (config.complexity_weight + config.size_weight)
    elif node.requires_review or node.role == "reviewer":
        tier, reason = "reviewer", "explicit review role"
        score = None if complexity is None or size is None else (
            config.complexity_weight * complexity + config.size_weight * size
        ) / (config.complexity_weight + config.size_weight)
    elif complexity is None or size is None:
        tier, score, reason = "expert", None, "uncertain signal safety floor"
    else:
        score = (
            config.complexity_weight * complexity + config.size_weight * size
        ) / (config.complexity_weight + config.size_weight)
        if score <= config.worker_max_score:
            tier, reason = "worker", "bounded score"
        elif score <= config.expert_max_score:
            tier, reason = "expert", "medium score"
        else:
            tier, reason = "lead", "complex score"
    settings = config.models[tier]
    return RoutingDecision(tier, settings.model, settings.reasoning_effort, score, reason)


CASES = (
    (NodeSignal("README typo", "worker", 0.05, 0.10), "worker"),
    (NodeSignal("unit validation rule", "worker", 0.20, 0.30), "worker"),
    (NodeSignal("API and persistence change", "worker", 0.45, 0.50), "expert"),
    (NodeSignal("cross-component feature", "worker", 0.80, 0.75), "lead"),
    (NodeSignal("security boundary", "security", 0.40, 0.30), "lead"),
    (NodeSignal("accepted-change review", "reviewer", 0.20, 0.30), "reviewer"),
    (NodeSignal("missing estimate", "worker", None, None), "expert"),
    (NodeSignal("partial estimate", "worker", None, 0.20), "expert"),
    (NodeSignal("root lead", "root", 0.05, 0.05), "lead"),
    (NodeSignal("integration checkpoint", "integration", 0.05, 0.05), "lead"),
)

INVALID_CASES = (
    NodeSignal("overweight estimate", "worker", 1.1, 0.2),
    NodeSignal("negative estimate", "worker", 0.2, -0.1),
    NodeSignal("non-finite estimate", "worker", math.nan, 0.2),
)


def run(config: RoutingConfig) -> int:
    started = time.perf_counter_ns()
    failures = []
    assignments = []
    for node, expected in CASES:
        decision = route_node(node, config)
        assignments.append(decision.tier)
        score = "n/a" if decision.score is None else f"{decision.score:.2f}"
        print(f"{node.name:28} score={score:>4} tier={decision.tier:8} model={decision.model} effort={decision.reasoning_effort}")
        if decision.tier != expected:
            failures.append(f"{node.name}: expected {expected}, got {decision.tier}")
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    passed = len(CASES) - len(failures)
    print(f"summary: {passed}/{len(CASES)} routing cases passed in {elapsed_ms:.2f} ms")
    if failures:
        raise AssertionError("; ".join(failures))
    distribution = Counter(assignments)
    non_lead = len(assignments) - distribution["lead"]
    print(
        "distribution: "
        f"worker={distribution['worker']} "
        f"expert={distribution['expert']} "
        f"lead={distribution['lead']} "
        f"reviewer={distribution['reviewer']} "
        f"non_lead={non_lead}/{len(assignments)}"
    )
    rejected = 0
    for node in INVALID_CASES:
        try:
            route_node(node, config)
        except ValueError:
            rejected += 1
        else:
            failures.append(f"{node.name}: invalid score was accepted")
    print(f"summary: {rejected}/{len(INVALID_CASES)} invalid score cases rejected")
    if failures:
        raise AssertionError("; ".join(failures))
    return 0


def main() -> int:
    default_config = Path(__file__).resolve().parents[1] / "plugins/code-canopy/skills/code-canopy/assets/codecanopy.toml"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=default_config)
    args = parser.parse_args()
    return run(load_config(args.config))


if __name__ == "__main__":
    raise SystemExit(main())
