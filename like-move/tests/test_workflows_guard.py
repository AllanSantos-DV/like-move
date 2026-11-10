"""GitHub Actions não roda suíte de teste nem runner Windows/macOS: a verificação é local.

python -m unittest discover -s tests -v   (a partir de like-move/)
"""

import glob
import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKFLOWS = sorted(
    glob.glob(os.path.join(REPO, ".github", "workflows", "*.yml"))
    + glob.glob(os.path.join(REPO, ".github", "workflows", "*.yaml"))
)
FORBIDDEN_RUNNER = re.compile(r"^\s*runs-on:.*\b(windows|macos)\b", re.IGNORECASE | re.MULTILINE)
TEST_COMMAND = re.compile(
    r"^\s*(?:-\s*)?run:.*\b(npm\s+(?:run\s+)?test|unittest|pytest|invoke-pester|node\s+--test|yarn\s+test|pnpm\s+test)\b",
    re.IGNORECASE | re.MULTILINE,
)
CALLS_LOCAL_WORKFLOW = re.compile(r"^\s*uses:\s*\./\.github/workflows/", re.MULTILINE)


class WorkflowsGuard(unittest.TestCase):
    def test_ha_workflows(self):
        self.assertTrue(WORKFLOWS)

    def test_sem_runner_windows_ou_macos(self):
        for path in WORKFLOWS:
            with open(path, encoding="utf-8") as f:
                self.assertIsNone(FORBIDDEN_RUNNER.search(f.read()), os.path.basename(path))

    def test_sem_comando_de_teste(self):
        for path in WORKFLOWS:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            self.assertIsNone(TEST_COMMAND.search(text), os.path.basename(path))
            self.assertIsNone(CALLS_LOCAL_WORKFLOW.search(text), os.path.basename(path))

    def test_o_guarda_pega_o_que_proibe(self):
        self.assertTrue(FORBIDDEN_RUNNER.search("    runs-on: windows-latest\n"))
        self.assertTrue(FORBIDDEN_RUNNER.search("    runs-on: macos-14\n"))
        self.assertTrue(TEST_COMMAND.search("        run: python -m unittest discover\n"))
        self.assertTrue(TEST_COMMAND.search("        run: npm test\n"))
        self.assertIsNone(FORBIDDEN_RUNNER.search("    runs-on: ubuntu-latest\n"))


if __name__ == "__main__":
    unittest.main()
