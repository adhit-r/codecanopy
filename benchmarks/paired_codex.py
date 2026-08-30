#!/usr/bin/env python3
"""Receipt-backed Codex-only paired benchmark; external execution is opt-in."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Mapping, Sequence

if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.providers import ProviderRequest, execute_provider, provider_capability


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
