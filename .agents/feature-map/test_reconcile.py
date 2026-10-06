import argparse
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import reconcile


class ReportTests(unittest.TestCase):
    def test_rejects_wrong_field_types(self) -> None:
        valid = {
            "changed": True,
            "summary": "Updated a reference",
            "for_integrator": [],
            "needs_human": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.json"
            report.write_text(json.dumps(valid))
            self.assertEqual(
                reconcile.read_report(report, reconcile.REPORT_KEYS), valid
            )
            for key, value in [
                ("changed", "false"),
                ("summary", None),
                ("for_integrator", "PATHS.md"),
                ("needs_human", None),
                ("needs_human", [42]),
            ]:
                with self.subTest(key=key, value=value):
                    report.write_text(json.dumps({**valid, key: value}))
                    self.assertIsNone(
                        reconcile.read_report(report, reconcile.REPORT_KEYS)
                    )
            report.write_text(json.dumps({"summary": "", "needs_human": "review"}))
            self.assertIsNone(reconcile.read_report(report, reconcile.INTEGRATE_KEYS))


class CommitLimitTests(unittest.TestCase):
    def test_oversized_range_does_not_run_agents_or_advance_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "RECONCILED"
            marker.write_text("base\n")
            args = argparse.Namespace(
                since=None,
                max_commits=2,
                write=True,
                rationale_file=Path(directory) / "rationale.md",
            )
            with (
                patch.object(reconcile, "MARKER", marker),
                patch.object(reconcile, "parse_args", return_value=args),
                patch.object(reconcile, "git", return_value="head"),
                patch.object(reconcile, "find_base", return_value="base"),
                patch.object(
                    reconcile,
                    "list_commits",
                    return_value=[("a", "oldest"), ("b", "middle"), ("c", "newest")],
                ),
                patch.object(
                    reconcile,
                    "build_plan",
                    return_value=({"base": "base", "head": "head", "commits": []}, {}),
                ),
                patch.object(reconcile, "revert_outside_map", return_value=[]),
                patch.object(reconcile, "map_changes", return_value=["PATHS.md"]),
                patch.object(
                    reconcile, "execute", return_value=reconcile.Outcome(False)
                ) as execute,
            ):
                self.assertEqual(reconcile.main(), 1)
                execute.assert_not_called()
            self.assertEqual(marker.read_text(), "base\n")


class EditBoundaryTests(unittest.TestCase):
    def test_restores_scripts_and_rejects_executable_documents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            map_dir = root / ".agents/feature-map"
            map_dir.mkdir(parents=True)
            doc = map_dir / "PATHS.md"
            script = map_dir / "reconcile.py"
            doc.write_text("original docs\n")
            script.write_text("original script\n")
            for args in [
                ["init", "-q"],
                ["add", "."],
                [
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.com",
                    "commit",
                    "-qm",
                    "fixture",
                ],
            ]:
                subprocess.run(
                    ["git", *args], cwd=root, check=True, capture_output=True
                )
            doc.write_text("updated docs\n")
            script.write_text("agent script edit\n")
            rogue = map_dir / "rogue.py"
            rogue.write_text("agent executable\n")
            with patch.object(reconcile, "REPO_ROOT", root):
                reverted = reconcile.revert_outside_map()
                self.assertIn(".agents/feature-map/reconcile.py", reverted)
                self.assertIn(".agents/feature-map/rogue.py", reverted)
                self.assertEqual(script.read_text(), "original script\n")
                self.assertFalse(rogue.exists())
                self.assertEqual(doc.read_text(), "updated docs\n")
                doc.chmod(0o755)
                reconcile.revert_outside_map()
                self.assertEqual(doc.read_text(), "original docs\n")


if __name__ == "__main__":
    unittest.main()
