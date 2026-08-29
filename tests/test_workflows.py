from pathlib import Path
import re
import unittest


class WorkflowSecurityTests(unittest.TestCase):
    def test_actions_are_pinned_to_full_commit_shas(self) -> None:
        for workflow in Path(".github/workflows").glob("*.yml"):
            for line in workflow.read_text(encoding="utf-8").splitlines():
                if "uses:" not in line:
                    continue
                reference = line.split("uses:", 1)[1].split("#", 1)[0].strip()
                self.assertRegex(reference, r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}$", workflow)


if __name__ == "__main__":
    unittest.main()
