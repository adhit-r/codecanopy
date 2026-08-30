from pathlib import Path
import os
import re
import tempfile
import unittest

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from runtime.safeio import read_regular_limited

_PINNED_REMOTE_ACTION = re.compile(
    r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_./-]+)?@[0-9a-f]{40}$"
)
MAX_WORKFLOW_BYTES = 1024 * 1024
MAX_WORKFLOW_YAML_NODES = 10_000


def _uses_references(node: Node | None, seen: set[int] | None = None):
    if node is None:
        return
    seen = set() if seen is None else seen
    identity = id(node)
    if identity in seen:
        return
    if len(seen) >= MAX_WORKFLOW_YAML_NODES:
        raise AssertionError("workflow YAML node limit exceeded")
    seen.add(identity)
    if isinstance(node, MappingNode):
        for key, value in node.value:
            if isinstance(key, ScalarNode) and key.value == "uses":
                if not isinstance(value, ScalarNode):
                    raise AssertionError("workflow uses value must be a scalar")
                yield value.value
            yield from _uses_references(value, seen)
    elif isinstance(node, SequenceNode):
        for value in node.value:
            yield from _uses_references(value, seen)


def _workflow_references(text: str):
    for document in yaml.compose_all(text, Loader=yaml.SafeLoader):
        yield from _uses_references(document)


def _read_workflow(path: Path) -> str:
    try:
        raw = read_regular_limited(path, MAX_WORKFLOW_BYTES)
    except ValueError as error:
        raise AssertionError(str(error)) from error
    if len(raw) > MAX_WORKFLOW_BYTES:
        raise AssertionError(f"workflow size limit exceeded: {path}")
    return raw.decode("utf-8")


class WorkflowSecurityTests(unittest.TestCase):
    def test_actions_are_pinned_to_full_commit_shas(self) -> None:
        workflows = Path(".github/workflows")
        for workflow in (path for path in workflows.iterdir() if path.suffix in {".yml", ".yaml"}):
            for reference in _workflow_references(_read_workflow(workflow)):
                if reference.startswith(("./", "docker://")):
                    continue
                self.assertRegex(reference, _PINNED_REMOTE_ACTION, workflow)

    def test_yaml_mapping_styles_cannot_bypass_uses_detection(self) -> None:
        workflow = """
steps:
  - uses: owner/standard@moving-tag
  - { uses: owner/flow@moving-tag }
  - "uses" : "owner/quoted@moving-tag"
  - ? uses
    : owner/explicit@moving-tag
"""
        self.assertEqual(
            [
                "owner/standard@moving-tag",
                "owner/flow@moving-tag",
                "owner/quoted@moving-tag",
                "owner/explicit@moving-tag",
            ],
            list(_workflow_references(workflow)),
        )

    def test_local_docker_and_pinned_reusable_workflow_references(self) -> None:
        allowed = (
            "./.github/actions/local",
            "docker://alpine:3.20",
            "owner/repo/.github/workflows/check.yml@0123456789abcdef0123456789abcdef01234567",
        )
        self.assertTrue(allowed[0].startswith("./"))
        self.assertTrue(allowed[1].startswith("docker://"))
        self.assertRegex(allowed[2], _PINNED_REMOTE_ACTION)

    def test_recursive_yaml_alias_does_not_loop(self) -> None:
        workflow = "recursive: &loop [*loop]\nsteps: [{ uses: owner/repo@moving-tag }]\n"
        self.assertEqual(["owner/repo@moving-tag"], list(_workflow_references(workflow)))

    def test_workflow_read_is_bounded_and_rejects_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            oversized = root / "oversized.yml"
            descriptor = os.open(oversized, os.O_WRONLY | os.O_CREAT, 0o600)
            try:
                os.ftruncate(descriptor, MAX_WORKFLOW_BYTES + 1)
            finally:
                os.close(descriptor)
            with self.assertRaisesRegex(AssertionError, "size limit"):
                _read_workflow(oversized)

            target = root / "target.yml"
            target.write_text("steps: []\n", encoding="utf-8")
            link = root / "linked.yml"
            link.symlink_to(target)
            with self.assertRaisesRegex(AssertionError, "unsafe input"):
                _read_workflow(link)


if __name__ == "__main__":
    unittest.main()
