# script to use as a kubernetes readiness / liveness probe

import argparse
import sys
import time
from pathlib import Path


def main_readiness(filename: str) -> int:
    """Checks if the file exists."""
    path = Path(filename)
    if not path.is_file():
        return 1

    return 0


def main_liveness(filename: str) -> int:
    """Checks if the file exists AND was recently modified."""
    path = Path(filename)
    if not path.is_file():
        return 1

    stats = path.stat()
    liveness_timestamp = stats.st_mtime
    current_timestamp = time.time()
    time_diff = current_timestamp - liveness_timestamp
    if time_diff > 60:
        return 1

    return 0


if __name__ == "__main__":
    exit_code: int

    parser = argparse.ArgumentParser(description="k8s readiness/liveness probe")
    parser.add_argument(
        "--probe",
        type=str,
        choices=["readiness", "liveness"],
        help="The type of probe",
        required=True,
    )
    parser.add_argument("--filename", help="The filename to watch", required=True)
    args = parser.parse_args()

    if args.probe == "readiness":
        exit_code = main_readiness(args.filename)
    elif args.probe == "liveness":
        exit_code = main_liveness(args.filename)
    else:
        raise ValueError(f"Unknown probe type: {args.probe}")

    sys.exit(exit_code)
