"""Constants and the `--workdir` argument shared by the mining scripts.

The shell scripts read the constants with `python3 common.py repo|workdir`.
"""

import argparse
import re
import sys
from pathlib import Path

REPO = "onyx-dot-app/onyx"
OWNER, NAME = REPO.split("/")
GRAPHQL_REPOSITORY = f'repository(owner: "{OWNER}", name: "{NAME}")'
REVIEWERS: frozenset[str] = frozenset({"wenxi-onyx", "evan-onyx", "Danelegend"})
BOTS = re.compile(
    r"\[bot\]$|^(coderabbitai|greptile-apps|cubic-dev-ai|devin-ai-integration)"
)
DEFAULT_WORKDIR = Path(__file__).resolve().parents[1] / ".cache" / "mining"


def parse_workdir(description: str | None) -> Path:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--workdir",
        type=Path,
        default=DEFAULT_WORKDIR,
        help="directory that holds corpus/ and swarm/ (default: %(default)s)",
    )
    return parser.parse_args().workdir.resolve()


if __name__ == "__main__":
    print({"repo": REPO, "workdir": DEFAULT_WORKDIR}[sys.argv[1]])
