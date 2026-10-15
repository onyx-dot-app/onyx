"""Exercise the public CI command and stdin transport, not VM behavior."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.common.paths import find_ancestor_containing

_REPO_ROOT = find_ancestor_containing("deployment/helm/dev")
_DOCKER = r"""
import json
import os
import subprocess
import sys

args = sys.argv[1:]
with open(os.environ["CLI_LOG"], "a") as log:
    log.write(json.dumps(["docker", *args]) + "\n")
if args[0] == "inspect":
    if "-f" in args:
        print("onyx-craft-ci")
elif args[0] == "cp":
    pass
elif args[:2] == ["exec", "onyx-craft-ci-control-plane"]:
    print("copied helper is absent from container /tmp", file=sys.stderr)
    sys.exit(1)
elif args[:5] == ["exec", "-i", "onyx-craft-ci-control-plane", "bash", "-s"]:
    payload = sys.stdin.buffer.read()
    result = subprocess.run(["bash", "-s", *args[5:]], input=payload)
    sys.exit(result.returncode)
else:
    raise AssertionError(args)
"""
_KUBECTL = r"""
import json
import os
import sys

with open(os.environ["CLI_LOG"], "a") as log:
    log.write(json.dumps(["kubectl", *sys.argv[1:]]) + "\n")
sys.exit(42)
"""


@pytest.mark.parametrize("helper_exit", [0, 17])
def test_public_verify_streams_helper_and_preserves_failure(
    tmp_path: Path, helper_exit: int
) -> None:
    commands = tmp_path / "bin"
    commands.mkdir()
    for name, source in (("docker", _DOCKER), ("kubectl", _KUBECTL)):
        command = commands / name
        command.write_text(f"#!{sys.executable}\n{source}")
        command.chmod(0o755)
    helper = tmp_path / "pin-helper.sh"
    helper.write_text(
        'set -euo pipefail\nprintf "PIN_HELPER_RECEIVED:%s\\n" "$1"\n'
        f"exit {helper_exit}\n"
    )
    log = tmp_path / "commands.jsonl"
    result = subprocess.run(
        ["bash", str(_REPO_ROOT / "deployment/helm/dev/firecracker-ci.sh"), "verify"],
        env={
            **os.environ,
            "PATH": f"{commands}:{os.environ['PATH']}",
            "CLI_LOG": str(log),
            "FIRECRACKER_PIN_HELPER": str(helper),
            "KIND_CLUSTER_NAME": "onyx-craft-ci",
            "KIND_NODE_NAME": "onyx-craft-ci-control-plane",
            "KATA_INSTALL_NODE_NAMES": "onyx-craft-ci-control-plane",
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == (helper_exit or 42), result.stdout + result.stderr
    assert result.stdout == "PIN_HELPER_RECEIVED:verify\n"
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert not any(call[:2] == ["docker", "cp"] for call in calls)
    assert any(call[0] == "kubectl" for call in calls) == (helper_exit == 0)
