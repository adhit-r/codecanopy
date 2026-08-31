from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from runtime.model_catalog import (
    ModelCatalogError,
    RoleModel,
    automatic_roles,
    load_role_settings,
    resolve_model_catalog,
)
from runtime.providers import _run_bounded


def _entry(model: str, *, default: bool = False, efforts: list[str] | None = None, **changes: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "model": model,
        "hidden": False,
        "availabilityNux": None,
        "isDefault": default,
        "modelSpecialty": None,
        "upgrade": None,
        "supportedReasoningEfforts": [
            {"reasoningEffort": effort, "description": effort} for effort in efforts or ["low", "medium", "high", "max", "ultra"]
        ],
    }
    entry.update(changes)
    return entry


def _catalog_output(entries: list[dict[str, object]], *, version: str = "0.1.0") -> str:
    return "\n".join(
        json.dumps(message)
        for message in (
            {"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"version": version}}},
            {"jsonrpc": "2.0", "method": "initialized", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "result": {"data": entries}},
        )
    )


def _runner(output: str):
    def run(command, *, cwd, env, timeout, input_data):
        del cwd, env
        assert command == ("/bin/codex", "app-server", "--stdio")
        assert timeout == 10
        messages = [json.loads(line) for line in input_data.decode("utf-8").splitlines()]
        assert messages == [
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
                "params": {"includeHidden": False, "limit": 100},
            },
        ]
        return subprocess.CompletedProcess(command, 0, output, "")

    return run


class ModelCatalogTests(unittest.TestCase):
    def test_codex_selects_current_structured_catalog_entries(self) -> None:
        entries = [
            _entry("frontier-next", default=True),
            _entry("balanced-next", efforts=["high", "ultra"]),
            _entry("economy-next", efforts=["medium", "max"]),
        ]
        catalog = resolve_model_catalog(
            "codex", automatic_roles(), which=lambda _: "/bin/codex", runner=_runner(_catalog_output(entries))
        )
        self.assertEqual("frontier-next", catalog.roles["lead"].model)
        self.assertEqual("balanced-next", catalog.roles["expert"].model)
        self.assertEqual("balanced-next", catalog.roles["reviewer"].model)
        self.assertEqual("economy-next", catalog.roles["worker"].model)
        self.assertEqual(64, len(catalog.catalog_hash))
        self.assertEqual("codex_app_server", catalog.source)
        self.assertEqual("0.1.0", catalog.source_version)

    def test_automatic_catalog_rejects_unsafe_or_incomplete_candidates(self) -> None:
        unsafe = (
            ("hidden", _entry("frontier-next", default=True, hidden=True)),
            ("availability", _entry("frontier-next", default=True, availabilityNux="unavailable")),
            ("specialty", _entry("frontier-next", default=True, modelSpecialty="research")),
            ("upgrade", _entry("frontier-next", default=True, upgrade="frontier-newer")),
            ("unsupported effort", _entry("frontier-next", default=True, efforts=["low"])),
        )
        for name, lead in unsafe:
            with self.subTest(name=name), self.assertRaises(ModelCatalogError):
                resolve_model_catalog(
                    "codex",
                    automatic_roles(),
                    which=lambda _: "/bin/codex",
                    runner=_runner(_catalog_output([lead])),
                )

    def test_rejects_an_unsafe_entry_even_when_other_roles_are_eligible(self) -> None:
        eligible = [
            _entry("frontier-next", default=True),
            _entry("balanced-next", efforts=["high", "ultra"]),
            _entry("economy-next", efforts=["medium", "max"]),
        ]
        unsafe = (
            _entry("hidden-next", hidden=True),
            _entry("notice-next", availabilityNux="unavailable"),
            _entry("specialty-next", modelSpecialty="research"),
            _entry("upgrade-next", upgrade="frontier-next"),
            _entry("empty-specialty", modelSpecialty=""),
            _entry("empty-upgrade", upgrade=""),
        )
        for entry in unsafe:
            with self.subTest(entry=entry["model"]), self.assertRaisesRegex(ModelCatalogError, "unsafe"):
                resolve_model_catalog(
                    "codex",
                    automatic_roles(),
                    which=lambda _: "/bin/codex",
                    runner=_runner(_catalog_output([*eligible, entry])),
                )

    def test_rejects_ambiguous_default_and_invalid_rpc_data(self) -> None:
        entries = [_entry("frontier-a", default=True), _entry("frontier-b", default=True)]
        with self.assertRaisesRegex(ModelCatalogError, "eligible lead"):
            resolve_model_catalog("codex", automatic_roles(), which=lambda _: "/bin/codex", runner=_runner(_catalog_output(entries)))

        invalid_outputs = (
            "not json",
            _catalog_output([_entry("frontier-next", default=True)]) + "\n" + "x" * (1024 * 1024),
            _catalog_output([_entry("frontier-next", default=True)] * 101),
            _catalog_output([_entry("frontier-next", default=True, supportedReasoningEfforts=["fast"])]),
        )
        for output in invalid_outputs:
            with self.subTest(output=output[:30]), self.assertRaises(ModelCatalogError):
                resolve_model_catalog("codex", automatic_roles(), which=lambda _: "/bin/codex", runner=_runner(output))

    def test_rejects_json_without_the_json_rpc_2_envelope(self) -> None:
        entries = [
            _entry("frontier-next", default=True),
            _entry("balanced-next", efforts=["high", "ultra"]),
            _entry("economy-next", efforts=["medium", "max"]),
        ]
        output = "\n".join(
            (
                json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}),
                json.dumps({"id": 2, "result": {"data": entries}}),
            )
        )
        with self.assertRaisesRegex(ModelCatalogError, "JSON-RPC"):
            resolve_model_catalog("codex", automatic_roles(), which=lambda _: "/bin/codex", runner=_runner(output))

    def test_claude_aliases_and_explicit_pins(self) -> None:
        claude = resolve_model_catalog("claude", automatic_roles(), which=lambda _: "/bin/claude")
        self.assertEqual(
            {"lead": "best", "expert": "sonnet", "reviewer": "sonnet", "worker": "haiku"},
            {role: value.model for role, value in claude.roles.items()},
        )
        settings = automatic_roles()
        settings["lead"] = RoleModel("controlled-rollout", "high")
        catalog = resolve_model_catalog("codex", settings, which=lambda _: "/bin/codex", runner=_runner(_catalog_output([
            _entry("frontier-next", default=True),
            _entry("balanced-next", efforts=["high", "ultra"]),
            _entry("economy-next", efforts=["medium", "max"]),
        ])))
        self.assertEqual(RoleModel("controlled-rollout", "high"), catalog.roles["lead"])

    def test_automatic_reviewer_reuses_a_pinned_expert(self) -> None:
        settings = automatic_roles()
        settings["expert"] = RoleModel("pinned-expert", "high")
        catalog = resolve_model_catalog("codex", settings, which=lambda _: "/bin/codex", runner=_runner(_catalog_output([
            _entry("frontier-next", default=True),
            _entry("balanced-next", efforts=["high", "ultra"]),
            _entry("economy-next", efforts=["medium", "max"]),
        ])))
        self.assertEqual("pinned-expert", catalog.roles["reviewer"].model)

    def test_missing_executable_and_invalid_config_fail_closed(self) -> None:
        with self.assertRaisesRegex(ModelCatalogError, "executable"):
            resolve_model_catalog("codex", automatic_roles(), which=lambda _: None)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "codecanopy.toml"
            path.write_text("[models.lead]\nmodel = 'bad/model'\nreasoning_effort = 'high'\n", encoding="utf-8")
            with self.assertRaisesRegex(ModelCatalogError, "models"):
                load_role_settings(path)

    def test_bounded_runner_writes_and_closes_json_rpc_input(self) -> None:
        completed = _run_bounded(
            (sys.executable, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"),
            cwd=None,
            env=dict(os.environ),
            timeout=2,
            input_data=b'{"jsonrpc":"2.0"}\n',
        )
        self.assertEqual((0, '{"jsonrpc":"2.0"}\n'), (completed.returncode, completed.stdout))
        with self.assertRaisesRegex(ValueError, "65536"):
            _run_bounded((sys.executable, "-c", "pass"), cwd=None, env=dict(os.environ), timeout=2, input_data=b"x" * 65537)
