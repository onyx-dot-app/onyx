# script to use as a kubernetes readiness / liveness probe

import argparse
import sys
from pathlib import Path


def main(filename: str) -> int:
    path = Path(filename)
    if not path.is_file():
        return 1

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="k8s readiness/liveness probe")
    parser.add_argument("--filename", help="The filename to watch", required=True)
    args = parser.parse_args()

    exit_code = main(args.filename)
    sys.exit(exit_code)
