"""Exercise the copy gate against real Git baselines and working catalogs."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CHECKER = Path(__file__).with_name("check_copy_changes.py").resolve()


class CopyChangesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.catalogs = self.root / "web/src/i18n/messages"
        self.catalogs.mkdir(parents=True)
        self.git("init", "-q")
        self.write("en", {"title": "Hello", "other": "Keep"})
        self.write("fr", {"title": "Bonjour", "other": "Garder"})
        self.write("de", {"title": "Hallo", "other": "Behalten"})
        self.git("add", ".")
        self.git(
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "baseline",
        )

    def git(self, *args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=self.root, text=True)

    def write(self, locale: str, messages: dict[str, str]) -> None:
        (self.catalogs / f"{locale}.json").write_text(json.dumps({"nested": messages}))

    def check(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CHECKER), *args],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_unchanged_copy_passes(self) -> None:
        self.assertEqual(self.check().returncode, 0)

    def test_requires_the_same_key_in_every_locale(self) -> None:
        self.write("en", {"title": "Welcome", "other": "Keep"})
        self.write("fr", {"title": "Bienvenue", "other": "Garder"})
        self.write("de", {"title": "Hallo", "other": "Anders"})
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("de: nested.title", result.stdout)
        self.assertNotIn("fr: nested.title", result.stdout)

    def test_updated_translations_pass(self) -> None:
        self.write("en", {"title": "Welcome"})
        self.write("fr", {"title": "Bienvenue"})
        self.write("de", {"title": "Willkommen"})
        self.assertEqual(self.check().returncode, 0)

    def test_missing_new_key_fails(self) -> None:
        self.write("en", {"title": "Hello", "new": "New"})
        self.assertIn("fr: nested.new", self.check().stdout)
        self.assertEqual(self.check().returncode, 1)

    def test_branch_base_checks_committed_copy(self) -> None:
        base = self.git("rev-parse", "HEAD").strip()
        self.write("en", {"title": "Welcome"})
        self.git("add", ".")
        self.git(
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "copy",
        )
        self.assertEqual(self.check().returncode, 0)
        self.assertEqual(self.check("--base", base).returncode, 1)

    def test_new_locale_has_no_previous_translation(self) -> None:
        self.write("en", {"title": "Welcome"})
        self.write("fr", {"title": "Bienvenue"})
        self.write("de", {"title": "Willkommen"})
        self.write("es", {"title": "Bienvenido"})
        self.assertEqual(self.check().returncode, 0)


if __name__ == "__main__":
    unittest.main()
