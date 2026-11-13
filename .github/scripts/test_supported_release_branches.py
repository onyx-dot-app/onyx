"""Exercise release selection against real Git refs."""

import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("supported-release-branches.py").resolve()


class ReleaseBranchesTest(unittest.TestCase):
    def test_numeric_release_lines_and_remote_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:

            def git(*args: str) -> str:
                return subprocess.check_output(
                    ["git", *args], cwd=directory, text=True, stderr=subprocess.PIPE
                ).strip()

            git("init", "-q")
            git(
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.com",
                "commit",
                "--allow-empty",
                "-qm",
                "fixture",
            )
            git("remote", "add", "origin", directory)
            for branch in [
                "release/v1.8",
                "release/v1.9",
                "release/v1.10",
                "release/v2.0",
                "release/v2.1",
                "release/v99.0-rc1",
            ]:
                git("branch", branch)
            result = subprocess.check_output(
                ["python3", str(SCRIPT)], cwd=directory, text=True
            )
            self.assertEqual(
                result.splitlines(),
                ["release/v1.9", "release/v1.10", "release/v2.0", "release/v2.1"],
            )
            git("remote", "remove", "origin")
            result = subprocess.run(
                ["python3", str(SCRIPT)], cwd=directory, capture_output=True
            )
            self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
