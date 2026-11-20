"""The update-feed check compares the OSes that run `tauri build` with the
`latest.json` platform keys, and honours an allow marker only with a reason."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_update_feed as check  # noqa: E402

_MATRIX_BUILD = """
jobs:
  build:
    strategy:
      matrix:
        include:
          - platform: windows-latest
          - platform: ubuntu-24.04
    runs-on: ${{ matrix.platform }}
    steps:
      - run: bun run tauri build
  mac:
    runs-on: macos-15
    steps:
      - run: bun run tauri build --target universal-apple-darwin
  publish:
    runs-on: ubuntu-latest
    steps:
      - run: echo upload
"""
_FEED = """
      - run: |
          jq -n '{platforms: {"darwin-aarch64": {}, "windows-x86_64": {}}}'
"""


class UpdateFeedTest(unittest.TestCase):
    def test_built_oses_come_from_build_jobs_and_matrix(self) -> None:
        import yaml

        self.assertEqual(
            check.built_oses(yaml.safe_load(_MATRIX_BUILD)),
            {"darwin", "windows", "linux"},
        )

    def test_os_without_a_feed_entry_fails(self) -> None:
        errors = check.check(_MATRIX_BUILD + _FEED)
        self.assertEqual(len(errors), 1)
        self.assertIn("linux", errors[0])

    def test_feed_key_in_a_comment_does_not_count(self) -> None:
        text = _MATRIX_BUILD + _FEED + '  # "linux-x86_64" is still to add\n'
        self.assertEqual(len(check.check(text)), 1)

    def test_allow_marker_exempts_and_needs_a_reason(self) -> None:
        allowed = _MATRIX_BUILD + _FEED + "# update-feed: allow linux updater is off\n"
        bare = _MATRIX_BUILD + _FEED + "# update-feed: allow linux\n"
        self.assertEqual(check.check(allowed), [])
        self.assertEqual(len(check.check(bare)), 2)


if __name__ == "__main__":
    unittest.main()
