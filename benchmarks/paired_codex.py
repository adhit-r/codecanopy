#!/usr/bin/env python3
"""Receipt-backed Codex-only paired benchmark; external execution is opt-in."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json
import math
import os
from pathlib import Path, PurePosixPath
from random import Random
import subprocess
import sys
import tempfile
from typing import Mapping, Sequence

if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.providers import (
    MAX_RECEIPT_EVENT_BYTES,
    ProviderRequest,
    execute_provider,
    provider_capability,
)
from runtime.safeio import open_private, read_regular_limited

try:  # ``fcntl`` is stdlib on the Unix hosts CodeCanopy currently supports.
    import fcntl
except ImportError:  # pragma: no cover - retained for importability elsewhere.
    fcntl = None


MAX_TOKEN_VALUE = 2**63 - 1
PROBE_PROMPT = "Return exactly OK."
CASE_ROOT = Path(__file__).with_name("cases") / "codex-readonly-v1"
_CASE_LIMITS = {"task": 16_384, "copy_manifest": 65_536, "dag": 65_536, "oracle": 65_536}
_MAX_SUBJECT_BYTES = 1_048_576
_CATEGORIES = frozenset({"correctness", "reliability", "security"})
_SEVERITIES = frozenset({"low", "medium", "high", "critical"})
MAX_MODEL_FINDINGS_BYTES = _CASE_LIMITS["oracle"]
MAX_RESULT_BYTES = 4 * 1024 * 1024
MAX_RESULT_EVENTS = 1_000
MAX_RESULT_EVENT_BYTES = 64 * 1024
_CASE_IDS = ("small", "medium", "complex")


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


def _hex_identity(value: object, lengths: set[int], label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) not in lengths
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} must be a lowercase hexadecimal identity")


def _validated_cases(cases: Sequence[CaseSnapshot]) -> tuple[CaseSnapshot, ...]:
    if len(cases) != len(_CASE_IDS) or any(not isinstance(case, CaseSnapshot) for case in cases):
        raise ValueError("benchmark schedule requires exactly three case snapshots")
    if any(not isinstance(case.case_id, str) for case in cases):
        raise ValueError("benchmark case ids must be strings")
    by_id = {case.case_id: case for case in cases}
    if set(by_id) != set(_CASE_IDS) or len(by_id) != len(cases):
        raise ValueError("benchmark schedule requires one snapshot for each fixed case")
    ordered = tuple(by_id[case_id] for case_id in _CASE_IDS)
    for case in ordered:
        _hex_identity(case.baseline, {40, 64}, "baseline")
        _hex_identity(case.subject_tree_hash, {40, 64}, "subject tree hash")
        _hex_identity(case.case_definition_hash, {64}, "case definition hash")
    return ordered


def _validate_run_contract(contract: RunContract) -> None:
    if not isinstance(contract, RunContract):
        raise ValueError("benchmark schedule requires a run contract")
    for field in (
        contract.benchmark_version,
        contract.scorer_version,
        contract.cli_version,
        contract.sandbox,
    ):
        if not isinstance(field, str) or not field:
            raise ValueError("run contract text fields must be non-empty strings")
    for value, label in (
        (contract.adapter_fingerprint, "adapter fingerprint"),
        (contract.routing_config_hash, "routing config hash"),
        (contract.acceptance_contract_hash, "acceptance contract hash"),
    ):
        _hex_identity(value, {64}, label)
    if (
        isinstance(contract.timeout_seconds, bool)
        or not isinstance(contract.timeout_seconds, (int, float))
        or not math.isfinite(contract.timeout_seconds)
        or contract.timeout_seconds <= 0
    ):
        raise ValueError("run contract timeout must be a positive finite number")


def build_schedule(
    seed: int,
    run_contract: RunContract,
    cases: Sequence[CaseSnapshot],
) -> BenchmarkSchedule:
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("benchmark seed must be an integer")
    _validate_run_contract(run_contract)
    case_snapshots = _validated_cases(cases)
    random = Random(seed)
    entries: list[ScheduleEntry] = []
    for case_id in _CASE_IDS:
        for repetition in range(1, 4):
            arms = ["sequential", "canopy"]
            random.shuffle(arms)
            entries.extend(
                ScheduleEntry(len(entries), case_id, repetition, arm)
                for arm in arms
            )
    return BenchmarkSchedule(seed, run_contract, case_snapshots, tuple(entries))


def append_result_record(path: str | Path, record: Mapping[str, object]) -> None:
    if not isinstance(record, Mapping) or any(not isinstance(key, str) for key in record):
        raise ValueError("benchmark result record must be a JSON object with string keys")
    try:
        serialized = json.dumps(
            dict(record), sort_keys=True, separators=(",", ":"), allow_nan=False
        ) + "\n"
    except (TypeError, ValueError) as error:
        raise ValueError("benchmark result record must be canonical JSON") from error
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


def _exact_mapping(value: object, keys: set[str], label: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"invalid benchmark {label}")
    return value


def _schedule_from_record(record: object) -> BenchmarkSchedule:
    row = _exact_mapping(
        record, {"kind", "seed", "run_contract", "cases", "entries"}, "schedule"
    )
    if row["kind"] != "schedule" or isinstance(row["seed"], bool) or not isinstance(row["seed"], int):
        raise ValueError("invalid benchmark schedule")
    contract = RunContract(**_exact_mapping(
        row["run_contract"],
        {
            "benchmark_version", "scorer_version", "cli_version", "adapter_fingerprint",
            "routing_config_hash", "timeout_seconds", "sandbox", "acceptance_contract_hash",
        },
        "run contract",
    ))
    raw_cases = row["cases"]
    raw_entries = row["entries"]
    if not isinstance(raw_cases, list) or not isinstance(raw_entries, list):
        raise ValueError("invalid benchmark schedule")
    cases = tuple(CaseSnapshot(**_exact_mapping(
        case,
        {"case_id", "baseline", "subject_tree_hash", "case_definition_hash"},
        "case snapshot",
    )) for case in raw_cases)
    entries: list[ScheduleEntry] = []
    for raw_entry in raw_entries:
        entry = _exact_mapping(
            raw_entry, {"position", "case_id", "repetition", "arm"}, "schedule entry"
        )
        if (
            isinstance(entry["position"], bool)
            or not isinstance(entry["position"], int)
            or isinstance(entry["repetition"], bool)
            or not isinstance(entry["repetition"], int)
            or not isinstance(entry["case_id"], str)
            or not isinstance(entry["arm"], str)
        ):
            raise ValueError("invalid benchmark schedule entry")
        entries.append(ScheduleEntry(**entry))
    schedule = BenchmarkSchedule(row["seed"], contract, cases, tuple(entries))
    expected = build_schedule(schedule.seed, schedule.run_contract, schedule.cases)
    if schedule != expected:
        raise ValueError("invalid benchmark schedule")
    return schedule


def load_results(path: str | Path) -> tuple[BenchmarkSchedule, tuple[Mapping[str, object], ...]]:
    with open_private(path, append=False) as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
        try:
            if os.fstat(handle.fileno()).st_size > MAX_RESULT_BYTES:
                raise ValueError("benchmark result size limit exceeded")
            payload = handle.read(MAX_RESULT_BYTES + 1)
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    if len(payload.encode("utf-8")) > MAX_RESULT_BYTES:
        raise ValueError("benchmark result size limit exceeded")
    lines = [line for line in payload.splitlines() if line.strip()]
    if not lines or len(lines) > MAX_RESULT_EVENTS:
        raise ValueError("benchmark result event limit exceeded")
    rows: list[Mapping[str, object]] = []
    for line in lines:
        if len((line + "\n").encode("utf-8")) > MAX_RESULT_EVENT_BYTES:
            raise ValueError("benchmark result event size limit exceeded")
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError("invalid benchmark result JSON") from error
        if not isinstance(row, dict):
            raise ValueError("benchmark result rows must be JSON objects")
        rows.append(row)
    schedule = _schedule_from_record(rows[0])
    records: list[Mapping[str, object]] = []
    for row in rows[1:]:
        if row.get("kind") == "schedule":
            raise ValueError("benchmark schedule must appear exactly once and first")
        if row.get("kind") != "arm-result":
            raise ValueError("invalid benchmark result kind")
        records.append(row)
    return schedule, tuple(records)


def audit_proof_receipt(state_root: str | Path, reference: str, output_hash: str) -> None:
    relative = _relative_path(reference)
    if relative != reference:
        raise ValueError("proof receipt reference must be canonical")
    path = Path(state_root).joinpath(*PurePosixPath(relative).parts)
    with open_private(path, append=False) as handle:
        size = os.fstat(handle.fileno()).st_size
        if size > MAX_RECEIPT_EVENT_BYTES:
            raise ValueError("proof receipt size limit exceeded")
        payload = handle.read(MAX_RECEIPT_EVENT_BYTES + 1)
    if len(payload.encode("utf-8")) > MAX_RECEIPT_EVENT_BYTES:
        raise ValueError("proof receipt size limit exceeded")
    rows = [line for line in payload.splitlines() if line.strip()]
    if len(rows) != 1:
        raise ValueError("proof receipt must contain exactly one row")
    try:
        row = json.loads(rows[0])
    except json.JSONDecodeError as error:
        raise ValueError("invalid proof receipt JSON") from error
    if not isinstance(row, dict):
        raise ValueError("proof receipt row must be a JSON object")
    if not isinstance(output_hash, str) or row.get("output_hash") != output_hash:
        raise ValueError("proof receipt output hash mismatch")


@dataclass(frozen=True)
class Finding:
    file: str
    start_line: int
    end_line: int
    category: str
    severity: str
    description: str


@dataclass(frozen=True)
class ParsedFindings:
    findings: tuple[Finding, ...] | None
    incomplete_reasons: tuple[str, ...]


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


def _read_exact_limited(path: Path, limit: int) -> bytes:
    payload = read_regular_limited(path, limit)
    if len(payload) > limit:
        raise ValueError(f"input exceeds {limit} byte limit: {path}")
    return payload


def _relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("path must be a non-empty POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) in ("", "."):
        raise ValueError("path must not be absolute or contain parent components")
    return path.as_posix()


def _case_path(root: Path, relative: str) -> Path:
    return root.joinpath(*PurePosixPath(relative).parts)


def _json_object(path: Path, limit: int, keys: set[str]) -> dict[str, object]:
    try:
        value = json.loads(_read_exact_limited(path, limit))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid JSON: {path}") from error
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"invalid JSON keys: {path}")
    return value


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field} must be a finite number")
    number = float(value)
    if not 0 <= number <= 1:
        raise ValueError(f"{field} must be between zero and one")
    return number


def _parse_findings(
    raw_findings: object,
    subject_paths: set[str],
    source_lines: Mapping[str, Sequence[str]],
    label: str,
) -> tuple[Finding, ...]:
    if not isinstance(raw_findings, list):
        raise ValueError(f"{label} findings must be a list")
    findings: list[Finding] = []
    intervals: dict[str, list[tuple[int, int]]] = {}
    for raw_finding in raw_findings:
        if not isinstance(raw_finding, dict) or set(raw_finding) != {
            "file", "start_line", "end_line", "category", "severity", "description"
        }:
            raise ValueError(f"{label} findings must use the exact finding schema")
        file = _relative_path(raw_finding["file"])
        start_line, end_line = raw_finding["start_line"], raw_finding["end_line"]
        category, severity, description = (
            raw_finding["category"], raw_finding["severity"], raw_finding["description"]
        )
        if file not in subject_paths:
            raise ValueError(f"{label} files must be manifest subject files")
        if (isinstance(start_line, bool) or not isinstance(start_line, int)
                or isinstance(end_line, bool) or not isinstance(end_line, int)
                or start_line < 1 or end_line < start_line):
            raise ValueError(f"{label} line range is invalid")
        if end_line > len(source_lines[file]):
            raise ValueError(f"{label} line range exceeds source file")
        if category not in _CATEGORIES or severity not in _SEVERITIES:
            raise ValueError(f"{label} category or severity is unknown")
        if not isinstance(description, str) or not description or len(description) > 8_192:
            raise ValueError(f"{label} description is invalid")
        if any(start_line <= prior_end and prior_start <= end_line
               for prior_start, prior_end in intervals.get(file, ())):
            raise ValueError(f"{label} findings must not overlap")
        intervals.setdefault(file, []).append((start_line, end_line))
        findings.append(Finding(file, start_line, end_line, category, severity, description))
    return tuple(findings)


def load_case_definition(case_directory: str | Path) -> CaseDefinition:
    root = Path(case_directory)
    task_bytes = _read_exact_limited(root / "task.txt", _CASE_LIMITS["task"])
    try:
        task = task_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("task must be UTF-8") from error
    if not task.strip():
        raise ValueError("task must not be blank")

    manifest = _json_object(root / "copy-manifest.json", _CASE_LIMITS["copy_manifest"], {"paths"})
    paths = manifest["paths"]
    if not isinstance(paths, list) or not paths:
        raise ValueError("manifest paths must be a non-empty list")
    copy_manifest = tuple(sorted(_relative_path(path) for path in paths))
    if len(set(copy_manifest)) != len(copy_manifest):
        raise ValueError("manifest paths must be unique")
    if any(path != "task.txt" and not path.startswith("subject/") for path in copy_manifest):
        raise ValueError("manifest may contain only task.txt and subject files")
    if "task.txt" not in copy_manifest:
        raise ValueError("manifest must contain task.txt")
    subject_paths = {path for path in copy_manifest if path.startswith("subject/")}
    if not subject_paths:
        raise ValueError("manifest must contain subject files")
    sources: dict[str, bytes] = {
        path: _read_exact_limited(_case_path(root, path), _MAX_SUBJECT_BYTES)
        for path in subject_paths
    }
    try:
        source_lines = {path: payload.decode("utf-8").splitlines() for path, payload in sources.items()}
    except UnicodeDecodeError as error:
        raise ValueError("subject files must be UTF-8") from error

    raw_dag = _json_object(root / "dag.json", _CASE_LIMITS["dag"], {"nodes"})
    raw_nodes = raw_dag["nodes"]
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise ValueError("DAG nodes must be a non-empty list")
    dag: list[DagNode] = []
    node_ids: set[str] = set()
    scopes: set[str] = set()
    for raw_node in raw_nodes:
        if not isinstance(raw_node, dict) or set(raw_node) != {
            "id", "role", "complexity_score", "size_score", "scope"
        }:
            raise ValueError("DAG nodes must use the exact node schema")
        node_id = raw_node["id"]
        role = raw_node["role"]
        raw_scope = raw_node["scope"]
        if not isinstance(node_id, str) or not node_id or node_id in node_ids:
            raise ValueError("DAG node ids must be non-empty and unique")
        if role not in {"worker", "security"}:
            raise ValueError("DAG roles must be worker or security")
        if not isinstance(raw_scope, list) or not raw_scope:
            raise ValueError("DAG scope must be a non-empty list")
        scope = tuple(_relative_path(path) for path in raw_scope)
        if len(set(scope)) != len(scope) or any(path not in subject_paths for path in scope):
            raise ValueError("DAG scopes must be unique manifest subject files")
        if scopes.intersection(scope):
            raise ValueError("DAG node scopes must be disjoint")
        node_ids.add(node_id)
        scopes.update(scope)
        dag.append(DagNode(
            node_id=node_id,
            role=role,
            complexity_score=_number(raw_node["complexity_score"], "complexity_score"),
            size_score=_number(raw_node["size_score"], "size_score"),
            scope=scope,
        ))
    if scopes != subject_paths:
        raise ValueError("DAG scopes must cover every manifest subject file")

    raw_oracle = _json_object(root / "oracle.json", _CASE_LIMITS["oracle"], {"findings"})
    oracle = _parse_findings(raw_oracle["findings"], subject_paths, source_lines, "oracle")

    return CaseDefinition(root.name, root, task, copy_manifest, tuple(dag), oracle)


def parse_model_findings(output: str, case: CaseDefinition) -> ParsedFindings:
    try:
        if len(output.encode("utf-8")) > MAX_MODEL_FINDINGS_BYTES:
            return ParsedFindings(None, ("model_findings_output_limit",))
        raw = json.loads(output)
        if not isinstance(raw, dict) or set(raw) != {"findings"}:
            raise ValueError("model findings must use the exact root schema")
        subject_paths = {path for path in case.copy_manifest if path.startswith("subject/")}
        source_lines = {
            path: _read_exact_limited(_case_path(case.root, path), _MAX_SUBJECT_BYTES)
            .decode("utf-8").splitlines()
            for path in subject_paths
        }
        return ParsedFindings(
            _parse_findings(raw["findings"], subject_paths, source_lines, "model"), ()
        )
    except (UnicodeError, json.JSONDecodeError, ValueError):
        return ParsedFindings(None, ("invalid_model_findings",))


def canonical_case_definition_hash(case: CaseDefinition) -> str:
    digests = {
        name: sha256(_read_exact_limited(path, _CASE_LIMITS[name])).hexdigest()
        for name, path in {
            "task": case.root / "task.txt",
            "copy_manifest": case.root / "copy-manifest.json",
            "dag": case.root / "dag.json",
            "oracle": case.root / "oracle.json",
        }.items()
    }
    payload = {"schema_version": 1, "digests": digests}
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def copy_case_repo(case: CaseDefinition, destination: str | Path) -> tuple[Path, str, str]:
    repo = Path(destination) / case.case_id
    if repo.exists():
        raise ValueError(f"baseline repository already exists: {repo}")
    repo.mkdir(parents=True)
    for path in case.copy_manifest:
        target = _case_path(repo, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        limit = _CASE_LIMITS["task"] if path == "task.txt" else _MAX_SUBJECT_BYTES
        target.write_bytes(_read_exact_limited(_case_path(case.root, path), limit))
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True, capture_output=True, text=True)
    for key, value in (("user.name", "CodeCanopy Benchmark"), ("user.email", "benchmark@codecanopy.invalid"),
                       ("core.autocrlf", "false")):
        subprocess.run(["git", "-C", str(repo), "config", key, value], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo), "add", "--all"], check=True, capture_output=True, text=True)
    environment = {
        **os.environ,
        "GIT_AUTHOR_NAME": "CodeCanopy Benchmark",
        "GIT_AUTHOR_EMAIL": "benchmark@codecanopy.invalid",
        "GIT_COMMITTER_NAME": "CodeCanopy Benchmark",
        "GIT_COMMITTER_EMAIL": "benchmark@codecanopy.invalid",
        "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
        "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
    }
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--quiet", "-m", "CodeCanopy benchmark baseline"],
        check=True, capture_output=True, text=True, env=environment,
    )
    baseline = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    tree_hash = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"], check=True, capture_output=True, text=True
    ).stdout.strip()
    return repo, baseline, tree_hash


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
OBSERVED_EVENT_KEYS: Mapping[str, frozenset[str]] = {
    "thread.started": frozenset({"type", "thread_id"}),
    "turn.started": frozenset({"type"}),
    "item.completed": frozenset({"type", "item"}),
    "turn.completed": frozenset({"type", "usage"}),
}


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
        expected_keys = OBSERVED_EVENT_KEYS.get(event["type"])
        if event["type"] not in adapter.observed_event_types:
            reasons.append("unknown_event_type")
        elif expected_keys is None or set(event) != expected_keys:
            reasons.append("unexpected_telemetry_shape")
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


def observe_invocation(
    output: str,
    *,
    cli_version: str | None,
    expected_adapter_fingerprint: str | None,
) -> InvocationObservation:
    observation = parse_jsonl(output)
    reasons = list(observation.incomplete_reasons)
    if cli_version != CODEX_0147.cli_version:
        reasons.append("cli_version_mismatch")
    if expected_adapter_fingerprint != adapter_fingerprint(CODEX_0147):
        reasons.append("adapter_fingerprint_mismatch")
    return replace(observation, incomplete_reasons=tuple(dict.fromkeys(reasons)))


def _probe_summary(*, execute: bool) -> dict[str, object]:
    return {
        "actual_model_available": False,
        "adapter_fingerprint": adapter_fingerprint(),
        "effort": "high",
        "execute": execute,
        "model": "gpt-5.6-sol",
        "provider": "codex",
        "sandbox": "read-only",
        "timeout": 120,
    }


def _print(data: Mapping[str, object]) -> None:
    print(json.dumps(data, sort_keys=True))


def _execute_probe() -> int:
    capability = provider_capability("codex", probe_version=True)
    if capability.version != CODEX_0147.cli_version:
        _print({**_probe_summary(execute=True), "incomplete_reasons": ["cli_version_mismatch"]})
        return 1
    with tempfile.TemporaryDirectory() as directory:
        repo = Path(directory) / "probe-repo"
        subprocess.run(["git", "init", "--quiet", str(repo)], check=True, capture_output=True, text=True)
        result = execute_provider(ProviderRequest(
            prompt=PROBE_PROMPT,
            preferred_provider="codex",
            timeout_seconds=120,
            cwd=repo,
            model="gpt-5.6-sol",
            reasoning_effort="high",
        ))
    observation = observe_invocation(
        result.output,
        cli_version=capability.version,
        expected_adapter_fingerprint=adapter_fingerprint(),
    )
    _print({
        **_probe_summary(execute=True),
        "exit_code": result.exit_code,
        "incomplete_reasons": list(observation.incomplete_reasons),
        "status": result.status,
        "tokens": {
            "cache_write_input_tokens": observation.cache_write_input_tokens,
            "cached_input_tokens": observation.cached_input_tokens,
            "input_tokens": observation.input_tokens,
            "output_tokens": observation.output_tokens,
            "reasoning_output_tokens": observation.reasoning_output_tokens,
            "total_tokens": observation.total_tokens,
        },
    })
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("probe",))
    parser.add_argument("--execute", action="store_true", help="run the opt-in local Codex probe")
    args = parser.parse_args(argv)
    if not args.execute:
        _print(_probe_summary(execute=False))
        return 0
    return _execute_probe()


if __name__ == "__main__":
    raise SystemExit(main())
