import importlib.util
import pathlib
import unittest

SPEC = importlib.util.spec_from_file_location(
    "desktop_downloads", pathlib.Path(__file__).with_name("desktop-downloads.py")
)
assert SPEC is not None and SPEC.loader is not None
downloads = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(downloads)


def asset(name: str, count: int) -> dict[str, object]:
    return {"name": name, "download_count": count}


class KindTest(unittest.TestCase):
    def test_classifies_the_release_assets(self) -> None:
        cases = {
            "Onyx_universal.dmg": ("macOS", "DMG"),
            "Onyx_universal.app.tar.gz": ("macOS", "Update archive"),
            "Onyx_x64.exe": ("Windows", "EXE x64"),
            "Onyx_arm64.exe": ("Windows", "EXE arm64"),
            "Onyx_x64.msi": ("Windows", "MSI"),
            "Onyx_amd64.deb": ("Linux", "DEB x64"),
            "Onyx_arm64.deb": ("Linux", "DEB arm64"),
            "Onyx_x86_64.rpm": ("Linux", "RPM x64"),
            "Onyx_aarch64.rpm": ("Linux", "RPM arm64"),
            "Onyx_amd64.AppImage": ("Linux", "AppImage"),
        }
        for name, expected in cases.items():
            self.assertEqual(downloads.kind(name), expected, name)

    def test_skips_signatures_and_other_assets(self) -> None:
        for name in (
            "Onyx_x64.exe.sig",
            "Onyx_universal.app.tar.gz.sig",
            "latest.json",
            "onyx-cli_linux_amd64.tar.gz",
            "Onyx_universal.txt",
        ):
            self.assertIsNone(downloads.kind(name), name)


class ReportTest(unittest.TestCase):
    def test_sums_per_release_and_platform(self) -> None:
        releases = [
            {
                "tag_name": "v1.0.0",
                "published_at": "2026-01-02T00:00:00Z",
                "draft": False,
                "assets": [
                    asset("Onyx_universal.dmg", 10),
                    asset("Onyx_x64.exe", 5),
                    asset("Onyx_x64.exe.sig", 99),
                    asset("Onyx_amd64.deb", 2),
                    asset("latest.json", 7),
                ],
            },
            {
                "tag_name": "v1.1.0",
                "published_at": "2026-02-02T00:00:00Z",
                "draft": False,
                "assets": [asset("Onyx_x64.msi", 3)],
            },
            {
                "tag_name": "v1.2.0",
                "published_at": None,
                "draft": True,
                "assets": [asset("Onyx_x64.msi", 100)],
            },
            {
                "tag_name": "cli/v1",
                "published_at": "2026-02-03T00:00:00Z",
                "draft": False,
                "assets": [asset("onyx-cli.tar.gz", 50)],
            },
        ]
        text = downloads.report(releases)
        self.assertIn("**20**", text)
        self.assertIn("| v1.0.0 | 2026-01-02 | 10 | 5 | 2 | 17 | 7 |", text)
        self.assertIn("| v1.1.0 | 2026-02-02 | 0 | 3 | 0 | 3 | 0 |", text)
        self.assertIn("| Windows | EXE x64 | 5 |", text)
        self.assertIn("automated downloads", text)
        self.assertNotIn("v1.2.0", text)
        self.assertNotIn("cli/v1", text)
        self.assertLess(text.index("v1.1.0"), text.index("v1.0.0"))


if __name__ == "__main__":
    unittest.main()
