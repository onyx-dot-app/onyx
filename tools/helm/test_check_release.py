"""Test the release gate against real Git repositories."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

CHECKER: Path = Path(__file__).with_name("check_release.py").resolve()
CHART: Path = Path("deployment/helm/charts/onyx/Chart.yaml")


class HelmReleaseTest(unittest.TestCase):
    def setUp(self) -> None:
        environment = patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        for key in ("GITHUB_BASE_REF", "GITHUB_REF"):
            os.environ.pop(key, None)
        self.temp: tempfile.TemporaryDirectory[str] = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root: Path = Path(self.temp.name)
        self.git("init", "-q", "-b", "main")
        self.git("config", "core.hooksPath", "/dev/null")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        (self.root / CHART.parent).mkdir(parents=True)
        self.metadata()
        self.values: Path = self.root / CHART.parent / "values.yaml"
        self.values.write_text("enabled: false\n")
        self.commit()
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.git("checkout", "-qb", "feature")

    def git(self, *args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=self.root, text=True)

    def commit(self) -> None:
        self.git("add", ".")
        self.git("commit", "-qm", "test")

    def metadata(
        self, version: str = "1.0.0", description: str = "Old release"
    ) -> None:
        (self.root / CHART).write_text(
            yaml.safe_dump(
                {
                    "version": version,
                    "description": "General chart purpose",
                    "annotations": {
                        "artifacthub.io/changes": yaml.safe_dump(
                            [{"kind": "changed", "description": description}]
                        )
                    },
                }
            )
        )

    def check(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CHECKER)],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_unchanged_and_outside_chart_changes_pass(self) -> None:
        self.assertEqual(self.check().returncode, 0)
        (self.root / "deployment/helm/README.md").write_text("New docs")
        self.assertEqual(self.check().returncode, 0)

    def test_values_change_needs_both_updates(self) -> None:
        self.values.write_text("enabled: true\n")
        result: subprocess.CompletedProcess[str] = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("Bump version", result.stdout)
        self.assertIn("release descriptions", result.stdout)
        self.metadata("1.0.1")
        self.assertEqual(self.check().returncode, 1)
        self.metadata("1.0.0", "Enable feature")
        self.assertEqual(self.check().returncode, 1)
        self.metadata("1.0.1", "Enable feature")
        self.assertEqual(self.check().returncode, 0)

    def test_deletion_requires_release(self) -> None:
        self.values.unlink()
        self.assertEqual(self.check().returncode, 1)

    def test_new_subchart_file_requires_parent_release(self) -> None:
        path: Path = self.root / "deployment/helm/charts/onyx-cnpg-crds/crds/new.yaml"
        path.parent.mkdir(parents=True)
        path.write_text("kind: CustomResourceDefinition\n")
        self.assertEqual(self.check().returncode, 1)
        self.metadata("1.0.1", "Add CRD")
        self.assertEqual(self.check().returncode, 0)

    def test_committed_changes_and_followup_use_branch_baseline(self) -> None:
        self.values.write_text("enabled: true\n")
        self.commit()
        self.assertEqual(self.check().returncode, 1)
        self.metadata("1.0.1", "Enable feature")
        self.commit()
        self.values.write_text("enabled: true\ncount: 2\n")
        self.assertEqual(self.check().returncode, 0)

    def test_main_only_changes_do_not_require_release(self) -> None:
        self.git("checkout", "-q", "main")
        self.values.write_text("enabled: true\n")
        self.metadata("1.0.1", "Main release")
        self.commit()
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.git("checkout", "-q", "feature")
        self.assertEqual(self.check().returncode, 0)
        self.metadata("1.0.1", "Conflicting release")
        self.assertEqual(self.check().returncode, 1)

    def test_release_branch_is_exempt(self) -> None:
        self.git("checkout", "-qb", "release/test")
        self.values.write_text("enabled: true\n")
        self.assertEqual(self.check().returncode, 0)

    def test_release_pr_is_exempt_in_detached_ci_checkout(self) -> None:
        self.git("checkout", "--detach", "-q")
        self.values.write_text("enabled: true\n")
        with patch.dict(os.environ, {"GITHUB_BASE_REF": "release/test"}):
            self.assertEqual(self.check().returncode, 0)

    def test_application_release_tag_is_exempt(self) -> None:
        self.values.write_text("enabled: true\n")
        self.commit()
        self.git("tag", "v1.0.0")
        self.git("checkout", "--detach", "-q", "v1.0.0")
        with patch.dict(os.environ, {"GITHUB_REF": "refs/tags/v1.0.0"}):
            self.assertEqual(self.check().returncode, 0)


if __name__ == "__main__":
    unittest.main()
