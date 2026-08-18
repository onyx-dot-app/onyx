#!/usr/bin/env python3
"""Fail if the public Terraform modules contain values that must stay internal.

These modules are published, but they are kept in sync with the infrastructure
Onyx runs. That makes it easy to carry an internal value across by accident --
an office IP in a variable default is the case this guard was written for.

The guard looks for objective patterns only: AWS account ids, access key ids,
and routable IPv4 CIDRs. It cannot screen for customer names, because listing
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

ACCOUNT_ID = re.compile(r"(?<!\d)\d{12}(?!\d)")
ACCESS_KEY = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")
IPV4_CIDR = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})/(\d{1,2})\b")


# Ranges that are safe to ship: private, loopback, link-local, carrier NAT,
# documentation, and the explicit "everywhere" wildcard.
def _is_publishable(network: ipaddress.IPv4Network) -> bool:
    if str(network) == "0.0.0.0/0":
        return True
    return not network.is_global


def scan(path: Path) -> list[str]:
    findings: list[str] = []
    for lineno, line in enumerate(path.read_text().splitlines(), start=1):
        if ALLOW_MARKER.search(line):
            continue
        try:
            shown = path.relative_to(ROOT)
        except ValueError:
            shown = path
        where = f"{shown}:{lineno}"

        if ACCESS_KEY.search(line):
            findings.append(f"{where}: AWS access key id")

        if ACCOUNT_ID.search(line):
            findings.append(
                f"{where}: 12-digit value that looks like an AWS account id"
            )

        for addr, prefix in IPV4_CIDR.findall(line):
            try:
                network = ipaddress.IPv4Network(f"{addr}/{prefix}", strict=False)
            except ValueError:
                continue
            if not _is_publishable(network):
                findings.append(f"{where}: routable IPv4 CIDR {addr}/{prefix}")
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
