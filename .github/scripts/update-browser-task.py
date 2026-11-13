"""Adapt the browser pin updater to the shared maintenance task workflow."""

import argparse
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--write", action="store_true", required=True)
parser.add_argument("--rationale-file", type=Path, required=True)
args = parser.parse_args()
installer = Path("backend/onyx/server/features/build/sandbox/image/install-browser.sh")
if installer.exists():
    version = subprocess.check_output(
        [
            "bash",
            str(Path(__file__).with_name("update-sandbox-browser.sh")),
            str(installer),
        ],
        text=True,
    ).strip()
    if version:
        args.rationale_file.write_text(
            f"\nUpdate Chrome to {version} with both archive checksums. "
            "CI uses the target branch’s checks. Backport browser audit and native "
            "rendering checks before merging release-branch updates.\n"
        )
