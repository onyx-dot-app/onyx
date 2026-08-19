#!/usr/bin/env python3
"""Fail if the public Terraform modules contain values that must stay internal.

These modules are published, but they are kept in sync with the infrastructure
Onyx runs. That makes it easy to carry an internal value across by accident --
an office IP in a variable default is the case this guard was written for.

The guard looks for objective patterns only: AWS account ids, access key ids,
routable IPv4 CIDRs, and email addresses. It cannot screen for customer names, because listing
them here would leak them; that stays a review step.

Add a trailing `# public-safe: ok` comment to accept a specific line.
"""

from __future__ import annotations

import ipaddress
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Must be the whole trailing comment token: "# public-safe: okay" does not count.
ALLOW_MARKER = re.compile(r"#\s*public-safe:\s*ok\s*$")

# One pass per line. Alternatives are ordered so the more specific pattern wins
# at a given position; the group name selects the message.
SUSPECT = re.compile(
    r"(?P<access_key>\b(?:AKIA|ASIA)[0-9A-Z]{16}\b)"
    r"|(?P<email>\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b)"
    r"|(?P<cidr>\b\d{1,3}(?:\.\d{1,3}){3}/\d{1,2}\b)"
    r"|(?P<account_id>(?<!\d)\d{12}(?!\d))"
)

MESSAGES = {
    "access_key": "AWS access key id",
    "email": "email address",
    "account_id": "12-digit value that looks like an AWS account id",
    "cidr": "routable IPv4 CIDR",
}


def _is_publishable(network: ipaddress.IPv4Network) -> bool:
    if str(network) == "0.0.0.0/0":
        return True
    return not network.is_global


def scan(path: Path) -> list[str]:
    findings: list[str] = []
    for lineno, line in enumerate(path.read_text().splitlines(), start=1):
        if ALLOW_MARKER.search(line):
            continue

        for match in SUSPECT.finditer(line):
            kind = match.lastgroup
            assert kind is not None
            value = match.group()

            # A private or reserved range is fine to ship; a routable one is not.
            if kind == "cidr":
                try:
                    network = ipaddress.IPv4Network(value, strict=False)
                except ValueError:
                    continue
                if _is_publishable(network):
                    continue

            try:
                shown = path.relative_to(ROOT)
            except ValueError:
                shown = path
            findings.append(f"{shown}:{lineno}: {MESSAGES[kind]} {value}".rstrip())
    return findings


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv[1:]] or sorted(ROOT.rglob("*.tf"))
    findings: list[str] = []
    for path in paths:
        if path.suffix != ".tf" or ".terraform" in path.parts:
            continue
        findings.extend(scan(path))

    if findings:
        print(
            "Internal values found in published Terraform modules:\n", file=sys.stderr
        )
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        print(
            "\nMove the value to the caller, or append '# public-safe: ok' if the "
            "line is genuinely safe to publish.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
