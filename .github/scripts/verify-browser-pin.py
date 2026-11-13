"""Accept only a version increase and its two checksum replacements."""

import re
import subprocess
import sys

INSTALLER = "backend/onyx/server/features/build/sandbox/image/install-browser.sh"
PIN = re.compile(
    r"^(version=[0-9]+(?:\.[0-9]+){3}|    checksum=[0-9a-f]{64})$", re.MULTILINE
)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def verify(base: str, head: str) -> None:
    ancestor = git("merge-base", base, head)
    if git("diff", "--name-only", ancestor, head) != INSTALLER:
        raise ValueError("A browser update must change only install-browser.sh")
    before = git("show", f"{ancestor}:{INSTALLER}")
    after = git("show", f"{head}:{INSTALLER}")
    old_pins, new_pins = PIN.findall(before), PIN.findall(after)
    if (
        len(old_pins) != 3
        or len(new_pins) != 3
        or PIN.sub("PIN", before) != PIN.sub("PIN", after)
    ):
        raise ValueError("A browser update must change only the version and two hashes")
    old_version = tuple(map(int, old_pins[0].removeprefix("version=").split(".")))
    new_version = tuple(map(int, new_pins[0].removeprefix("version=").split(".")))
    if new_version <= old_version:
        raise ValueError("A browser update must increase the version")
    if any(old == new for old, new in zip(old_pins[1:], new_pins[1:], strict=True)):
        raise ValueError("A browser update must change both checksums")


if __name__ == "__main__":
    verify(sys.argv[1], sys.argv[2])
