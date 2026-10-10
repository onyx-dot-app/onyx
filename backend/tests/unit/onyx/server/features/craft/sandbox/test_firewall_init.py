"""Run the firewall bootstrap with controlled DNS and firewall commands."""

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

_SCRIPT: Path = (
    Path(__file__).resolve().parents[7]
    / "onyx/server/features/build/sandbox/image/firewall-init.sh"
)

# This command substitute stores installed rules. A dropped rule therefore
# fails the script's real verification, rather than a mocked verification.
_COMMAND: str = r"""
import json
import os
import sys
from pathlib import Path
from typing import TypedDict

class Table(TypedDict):
    policy: str
    rules: list[list[str]]

class State(TypedDict):
    calls: list[list[str]]
    tables: dict[str, Table]

name: str = Path(sys.argv[0]).name
args: list[str] = sys.argv[1:]
state_path: Path = Path(os.environ["FIREWALL_STATE"])
state: State = json.loads(state_path.read_text())
state["calls"].append([name, *args])
exit_code: int = 0
if name == "getent":
    answer: str = os.environ.get("DNS_V4" if args[0] == "ahostsv4" else "DNS_V6", "")
    print(answer)
    exit_code = 0 if answer else 2
elif name in ("iptables", "ip6tables"):
    table: Table = state["tables"].setdefault(name, {"policy": "ACCEPT", "rules": []})
    operation: str = args[0]
    if operation == "-F":
        table["rules"] = []
    elif operation == "-P" and args[1] == "OUTPUT":
        if os.environ.get("MISSING_RULE") != args[2]:
            table["policy"] = args[2]
    elif operation == "-A":
        rule: list[str] = args[1:]
        missing: str = os.environ.get("MISSING_RULE", "")
        if not (missing and missing in rule):
            table["rules"].append(rule)
    elif operation == "-S":
        print("-P OUTPUT " + table["policy"])
    elif operation == "-C":
        exit_code = 0 if args[1:] in table["rules"] else 1
state_path.write_text(json.dumps(state))
sys.exit(exit_code)
"""


@dataclass
class FirewallRun:
    process: subprocess.CompletedProcess[str]
    calls: list[list[str]]

    def rules(self, table: str) -> list[list[str]]:
        return [call[2:] for call in self.calls if call[:2] == [table, "-A"]]


@pytest.fixture
def firewall_commands(tmp_path: Path) -> dict[str, str]:
    command: Path = tmp_path / "command"
    command.write_text(f"#!{sys.executable}\n{_COMMAND}")
    command.chmod(0o755)
    name: str
    for name in (
        "iptables",
        "ip6tables",
        "getent",
        "install",
        "update-ca-certificates",
    ):
        (tmp_path / name).symlink_to(command)
    state: Path = tmp_path / "state.json"
    state.write_text('{"calls": [], "tables": {}}')
    ca: Path = tmp_path / "ca.crt"
    ca.touch()
    return {
        **os.environ,
        "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        "FIREWALL_STATE": str(state),
        "SANDBOX_PROXY_BOOTSTRAP_MODE": "initcontainer",
        "SANDBOX_PROXY_HOST": "proxy.example.test",
        "SANDBOX_PROXY_PORT": "8080",
        "SANDBOX_PROXY_CA_BUNDLE_SRC": str(ca),
        "SANDBOX_PROXY_CA_BUNDLE_DST": str(tmp_path / "ca-bundle.crt"),
        "DNS_V4": "",
        "DNS_V6": "",
        "MISSING_RULE": "",
    }


def _run(env: dict[str, str]) -> FirewallRun:
    process: subprocess.CompletedProcess[str] = subprocess.run(
        ["bash", str(_SCRIPT)], env=env, capture_output=True, text=True, timeout=15
    )
    calls: list[list[str]] = json.loads(Path(env["FIREWALL_STATE"]).read_text())[
        "calls"
    ]
    return FirewallRun(process, calls)


@pytest.mark.parametrize(
    "proxy_ip,table", [("10.96.0.2", "iptables"), ("fd00::2", "ip6tables")]
)
def test_literal_proxy_locks_down_both_families(
    firewall_commands: dict[str, str], proxy_ip: str, table: str
) -> None:
    firewall_commands["SANDBOX_PROXY_HOST"] = proxy_ip
    run: FirewallRun = _run(firewall_commands)
    assert run.process.returncode == 0, run.process.stderr
    assert not any(call[0] == "getent" for call in run.calls)
    family: str
    for family in ("iptables", "ip6tables"):
        assert [family, "-P", "OUTPUT", "DROP"] in run.calls
        rules: list[list[str]] = run.rules(family)
        destinations: list[list[str]] = [rule for rule in rules if "-d" in rule]
        assert destinations == (
            [["OUTPUT", "-p", "tcp", "-d", proxy_ip, "--dport", "8080", "-j", "ACCEPT"]]
            if family == table
            else []
        )
        assert rules[-1][-2:] == [
            "--reject-with",
            "icmp-admin-prohibited" if family == "iptables" else "icmp6-adm-prohibited",
        ]
    nd_rules: list[list[str]] = [
        rule for rule in run.rules("ip6tables") if "--icmpv6-type" in rule
    ]
    assert len(nd_rules) == 2
    assert {rule[rule.index("--icmpv6-type") + 1] for rule in nd_rules} == {
        "135",
        "136",
    }
    assert all(rule[rule.index("--hl-eq") + 1] == "255" for rule in nd_rules)


@pytest.mark.parametrize("ipv4", [True, False])
def test_dns_prefers_ipv4_and_falls_back_to_aaaa(
    firewall_commands: dict[str, str], ipv4: bool
) -> None:
    firewall_commands["DNS_V4"] = (
        "10.96.0.2 STREAM proxy\n10.96.0.2 DGRAM proxy" if ipv4 else ""
    )
    firewall_commands["DNS_V6"] = "fd00::2 proxy"
    run: FirewallRun = _run(firewall_commands)
    assert run.process.returncode == 0, run.process.stderr
    queries: list[str] = [call[1] for call in run.calls if call[0] == "getent"]
    assert queries == (["ahostsv4"] if ipv4 else ["ahostsv4", "hosts"])
    table: str
    address: str
    table, address = ("iptables", "10.96.0.2") if ipv4 else ("ip6tables", "fd00::2")
    assert any("-d" in rule and address in rule for rule in run.rules(table))


def test_dns_failure_stops_before_firewall_changes(
    firewall_commands: dict[str, str],
) -> None:
    run: FirewallRun = _run(firewall_commands)
    assert run.process.returncode != 0
    assert "could not resolve proxy host" in run.process.stderr
    assert not any(call[0] in ("iptables", "ip6tables") for call in run.calls)


@pytest.mark.parametrize(
    "missing_rule,error",
    [
        ("--dport", "proxy ACCEPT rule missing"),
        ("135", "neighbor discovery rule missing"),
        ("136", "neighbor discovery rule missing"),
        ("lo", "loopback rule missing"),
        ("conntrack", "conntrack rule missing"),
        ("DROP", "OUTPUT default policy is not DROP"),
    ],
)
def test_missing_required_rule_fails_bootstrap(
    firewall_commands: dict[str, str], missing_rule: str, error: str
) -> None:
    firewall_commands["SANDBOX_PROXY_HOST"] = "fd00::2"
    firewall_commands["MISSING_RULE"] = missing_rule
    run: FirewallRun = _run(firewall_commands)
    assert run.process.returncode != 0
    assert error in run.process.stderr
    assert "bootstrap complete" not in run.process.stderr
