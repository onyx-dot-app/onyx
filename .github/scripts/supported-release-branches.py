"""Print the four newest numeric release branches, oldest first."""

import re
import subprocess


def main() -> None:
    heads = subprocess.check_output(
        ["git", "ls-remote", "--heads", "origin", "refs/heads/release/v*"], text=True
    )
    branches: dict[tuple[int, int], str] = {}
    for line in heads.splitlines():
        match = re.fullmatch(r"[0-9a-f]+\s+refs/heads/(release/v(\d+)\.(\d+))", line)
        if match:
            branches[int(match[2]), int(match[3])] = match[1]
    for version in sorted(branches)[-4:]:
        print(branches[version])


if __name__ == "__main__":
    main()
