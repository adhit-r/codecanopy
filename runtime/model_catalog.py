"""Resolve the provider's current general-purpose models once per tree run."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
from types import MappingProxyType
from typing import Callable, Mapping

from .providers import (
    MAX_PROVIDER_OUTPUT_BYTES,
    MODEL_ID,
    REASONING_EFFORTS,
    ProviderName,
    _provider_environment,
    _run_bounded,
)


ROLE_NAMES = ("lead", "expert", "reviewer", "worker")
CLAUDE_ALIASES = {"lead": "best", "expert": "sonnet", "reviewer": "sonnet", "worker": "haiku"}
DISCOVERY_TIMEOUT_SECONDS = 10
MAX_CATALOG_ENTRIES = 100


class ModelCatalogError(ValueError):
    """The provider catalog is unavailable, malformed, or unsafe to use."""


@dataclass(frozen=True)
class RoleModel:
    model: str
    reasoning_effort: str


@dataclass(frozen=True)
class ResolvedCatalog:
    provider: ProviderName
    source: str
    source_version: str | None
    roles: Mapping[str, RoleModel]
    catalog_hash: str


@dataclass(frozen=True)
class _CodexModel:
    model: str
    efforts: frozenset[str]
    is_default: bool


def automatic_roles() -> dict[str, RoleModel]:
    """Return the bundled role effort defaults with provider-selected models."""
    return {
        "lead": RoleModel("auto", "high"),
        "expert": RoleModel("auto", "high"),
        "reviewer": RoleModel("auto", "high"),
        "worker": RoleModel("auto", "medium"),
    }


def load_role_settings(path: str | Path) -> dict[str, RoleModel]:
    """Load and validate the model settings portion of a CodeCanopy TOML file."""
    try:
        with Path(path).open("rb") as file:
            config = tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ModelCatalogError(f"invalid model config: {error}") from error
    if not isinstance(config, dict):  # pragma: no cover - tomllib always returns a dict.
        raise ModelCatalogError("invalid model config")
    _validate_discovery_config(config.get("model_discovery"))
    return _coerce_role_settings(config.get("models"))


def resolve_model_catalog(
    provider: ProviderName,
    role_settings: Mapping[str, RoleModel],
    *,
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., subprocess.CompletedProcess[str]] = _run_bounded,
) -> ResolvedCatalog:
    """Freeze safe automatic selections or validated explicit role pins."""
    if provider not in ("codex", "claude"):
        raise ModelCatalogError(f"unsupported provider: {provider}")
    settings = _coerce_role_settings(role_settings)
    executable = which(provider)
    if not isinstance(executable, str) or not executable:
        raise ModelCatalogError(f"{provider} provider executable is unavailable")
    if provider == "claude":
        roles = {
            role: setting if setting.model != "auto" else RoleModel(CLAUDE_ALIASES[role], setting.reasoning_effort)
            for role, setting in settings.items()
        }
        return _catalog("claude", "claude_aliases", None, roles)
    return _resolve_codex(executable, settings, runner)


def _resolve_codex(
    executable: str,
    settings: Mapping[str, RoleModel],
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> ResolvedCatalog:
    input_data = b"\n".join(
        json.dumps(message, separators=(",", ":")).encode("utf-8")
        for message in (
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"clientInfo": {"name": "code-canopy", "version": "1"}, "capabilities": {}},
            },
            {"jsonrpc": "2.0", "method": "initialized", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "model/list",
                "params": {"includeHidden": False, "limit": MAX_CATALOG_ENTRIES},
            },
        )
    ) + b"\n"
    try:
        completed = runner(
            (executable, "app-server", "--stdio"),
            cwd=None,
            env=_provider_environment("codex"),
            timeout=DISCOVERY_TIMEOUT_SECONDS,
            input_data=input_data,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        raise ModelCatalogError("Codex model discovery failed") from error
    if not isinstance(completed, subprocess.CompletedProcess) or completed.returncode != 0:
        raise ModelCatalogError("Codex model discovery failed")
    responses = _json_rpc_responses(completed.stdout)
    initialize = responses[1]
    listed = responses[2]
    entries = listed.get("data") if isinstance(listed, dict) else None
    if not isinstance(entries, list) or not entries or len(entries) > MAX_CATALOG_ENTRIES:
        raise ModelCatalogError("Codex model/list returned an invalid catalog")
    next_cursor = listed.get("nextCursor")
    if next_cursor is not None:
        if not isinstance(next_cursor, str):
            raise ModelCatalogError("Codex model/list returned an invalid catalog")
        raise ModelCatalogError("Codex model/list exceeded the catalog limit")
    candidates = tuple(_parse_candidate(entry) for entry in entries)
    roles = _resolve_codex_roles(settings, candidates)
    server_info = initialize.get("serverInfo") if isinstance(initialize, dict) else None
    version = initialize.get("version") if isinstance(initialize, dict) else None
    if version is None and isinstance(server_info, dict):
        version = server_info.get("version")
    if version is None and isinstance(initialize, dict):
        version = initialize.get("userAgent")
    if version is not None and not isinstance(version, str):
        raise ModelCatalogError("Codex initialize returned an invalid version")
    return _catalog("codex", "codex_app_server", version, roles)


def _json_rpc_responses(output: object) -> dict[int, dict[str, object]]:
    if not isinstance(output, str) or len(output.encode("utf-8")) > MAX_PROVIDER_OUTPUT_BYTES:
        raise ModelCatalogError("Codex JSON-RPC output is malformed or oversized")
    responses: dict[int, dict[str, object]] = {}
    for line in output.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError as error:
            raise ModelCatalogError("Codex JSON-RPC output is malformed") from error
        if not isinstance(message, dict):
            raise ModelCatalogError("Codex JSON-RPC output is malformed")
        identifier = message.get("id")
        if type(identifier) is int and identifier in (1, 2):
            if identifier in responses or "error" in message or not isinstance(message.get("result"), dict):
                raise ModelCatalogError("Codex JSON-RPC response is invalid")
            responses[identifier] = message["result"]
    if set(responses) != {1, 2}:
        raise ModelCatalogError("Codex JSON-RPC responses are incomplete")
    return responses


def _parse_candidate(value: object) -> _CodexModel | None:
    if not isinstance(value, dict):
        raise ModelCatalogError("Codex model entry is malformed")
    model = value.get("model")
    hidden = value.get("hidden")
    is_default = value.get("isDefault")
    efforts = value.get("supportedReasoningEfforts")
    if not isinstance(model, str) or not MODEL_ID.fullmatch(model):
        raise ModelCatalogError("Codex model entry has an invalid model identifier")
    if not isinstance(hidden, bool) or not isinstance(is_default, bool):
        raise ModelCatalogError("Codex model entry is malformed")
    normalized_efforts = _reasoning_efforts(efforts)
    if normalized_efforts is None:
        raise ModelCatalogError("Codex model entry has invalid reasoning efforts")
    notices = tuple(_marker(value, name) for name in ("availabilityNux", "modelSpecialty", "upgrade"))
    if hidden or any(notice for notice in notices):
        return None
    return _CodexModel(model, normalized_efforts, is_default)


def _reasoning_efforts(value: object) -> frozenset[str] | None:
    if not isinstance(value, list) or not value:
        return None
    if all(isinstance(item, str) for item in value):
        efforts = value
    elif all(isinstance(item, Mapping) for item in value):
        efforts = [item.get("reasoningEffort") for item in value]
    else:
        return None
    if any(not isinstance(effort, str) or effort not in REASONING_EFFORTS for effort in efforts):
        return None
    return frozenset(efforts)


def _marker(entry: Mapping[str, object], name: str) -> str | None:
    value = entry.get(name)
    if value is None:
        return None
    if name == "availabilityNux" and isinstance(value, Mapping):
        if set(value) != {"message"} or not isinstance(value.get("message"), str):
            raise ModelCatalogError("Codex model entry has an invalid availabilityNux")
        return value["message"] or "notice"
    if not isinstance(value, str):
        raise ModelCatalogError(f"Codex model entry has an invalid {name}")
    return value or None


def _resolve_codex_roles(
    settings: Mapping[str, RoleModel], candidates: tuple[_CodexModel | None, ...]
) -> dict[str, RoleModel]:
    eligible = tuple(candidate for candidate in candidates if candidate is not None)
    roles = {role: setting for role, setting in settings.items() if setting.model != "auto"}
    if settings["lead"].model == "auto":
        defaults = [candidate for candidate in eligible if candidate.is_default and settings["lead"].reasoning_effort in candidate.efforts]
        if len(defaults) != 1:
            raise ModelCatalogError("Codex catalog has no unique eligible lead")
        roles["lead"] = RoleModel(defaults[0].model, settings["lead"].reasoning_effort)
    expert = next(
        (
            candidate
            for candidate in eligible
            if not candidate.is_default
            and "ultra" in candidate.efforts
            and all(
                settings[role].reasoning_effort in candidate.efforts
                for role in ("expert", "reviewer")
                if settings[role].model == "auto"
            )
        ),
        None,
    )
    if any(settings[role].model == "auto" for role in ("expert", "reviewer")):
        if expert is None:
            raise ModelCatalogError("Codex catalog has no eligible expert")
        for role in ("expert", "reviewer"):
            if settings[role].model == "auto":
                roles[role] = RoleModel(expert.model, settings[role].reasoning_effort)
    if settings["worker"].model == "auto":
        worker = next(
            (
                candidate
                for candidate in eligible
                if not candidate.is_default
                and "max" in candidate.efforts
                and "ultra" not in candidate.efforts
                and settings["worker"].reasoning_effort in candidate.efforts
            ),
            None,
        )
        if worker is None:
            raise ModelCatalogError("Codex catalog has no eligible worker")
        roles["worker"] = RoleModel(worker.model, settings["worker"].reasoning_effort)
    return {role: roles[role] for role in ROLE_NAMES}


def _coerce_role_settings(value: object) -> dict[str, RoleModel]:
    if not isinstance(value, Mapping) or set(value) != set(ROLE_NAMES):
        raise ModelCatalogError("models must define lead, expert, reviewer, and worker")
    roles: dict[str, RoleModel] = {}
    for role in ROLE_NAMES:
        setting = value[role]
        if isinstance(setting, RoleModel):
            model, effort = setting.model, setting.reasoning_effort
        elif isinstance(setting, Mapping):
            model, effort = setting.get("model"), setting.get("reasoning_effort")
        else:
            raise ModelCatalogError(f"models.{role} is invalid")
        if not isinstance(model, str) or (model != "auto" and not MODEL_ID.fullmatch(model)):
            raise ModelCatalogError(f"models.{role}.model is invalid")
        if not isinstance(effort, str) or effort not in REASONING_EFFORTS:
            raise ModelCatalogError(f"models.{role}.reasoning_effort is invalid")
        roles[role] = RoleModel(model, effort)
    return roles


def _validate_discovery_config(value: object) -> None:
    if value is None:
        return
    expected = {"mode": "automatic", "release_channel": "ga", "refresh": "run_start", "on_failure": "fail"}
    if not isinstance(value, Mapping) or any(value.get(key) != expected[key] for key in expected):
        raise ModelCatalogError("invalid model_discovery config")


def _catalog(
    provider: ProviderName, source: str, source_version: str | None, roles: Mapping[str, RoleModel]
) -> ResolvedCatalog:
    frozen_roles = MappingProxyType(dict(roles))
    payload = {
        "provider": provider,
        "source": source,
        "source_version": source_version,
        "roles": {role: asdict(frozen_roles[role]) for role in ROLE_NAMES},
    }
    catalog_hash = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return ResolvedCatalog(provider, source, source_version, frozen_roles, catalog_hash)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("codex", "claude"), required=True)
    parser.add_argument("--config", required=True)
    arguments = parser.parse_args(argv)
    catalog = resolve_model_catalog(arguments.provider, load_role_settings(arguments.config))
    json.dump(
        {
            "provider": catalog.provider,
            "source": catalog.source,
            "source_version": catalog.source_version,
            "roles": {role: asdict(value) for role, value in catalog.roles.items()},
            "catalog_hash": catalog.catalog_hash,
        },
        sys.stdout,
        sort_keys=True,
        separators=(",", ":"),
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI.
    raise SystemExit(main())
