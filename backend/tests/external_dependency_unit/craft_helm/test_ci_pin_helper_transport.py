"""Exercise the public CI command and stdin transport, not VM behavior."""

import json
import shutil
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
    if args[2] == "findmnt":
        print("devtmpfs")
    elif args[2:4] == ["bash", "-c"]:
        print("stop at snapshot probe prerequisites", file=sys.stderr)
        sys.exit(42)
    else:
        raise AssertionError(args)
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
    for name in ("awk", "bash", "cat", "dirname"):
        executable = shutil.which(name)
        assert executable is not None, f"required fixture tool {name} is missing"
        (commands / name).symlink_to(executable)
    for name in (
        "blockdev",
        "containerd",
        "ctr",
        "curl",
        "dmsetup",
        "docker",
        "findmnt",
        "helm",
        "kind",
        "kubectl",
        "limactl",
        "losetup",
        "modprobe",
        "mount",
        "ssh",
        "stat",
        "sudo",
        "systemctl",
        "umount",
        "wget",
    ):
        command = commands / name
        command.write_text(f"#!{sys.executable}\nraise SystemExit(99)\n")
        command.chmod(0o755)
    for name, source in (
        ("docker", _DOCKER),
        ("kubectl", _KUBECTL),
        ("findmnt", 'print("devtmpfs")'),
        ("blockdev", "raise AssertionError('host blockdev must not run')"),
    ):
        command = commands / name
        command.write_text(f"#!{sys.executable}\n{source}")
        command.chmod(0o755)
    helper = tmp_path / "pin-helper.sh"
    helper.write_text(
        'set -euo pipefail\nprintf "PIN_HELPER_RECEIVED:%s\\n" "$1"\n'
        f"exit {helper_exit}\n"
    )
    log = tmp_path / "commands.jsonl"
    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.write_text(
        "apiVersion: v1\nkind: Config\nclusters: []\ncontexts: []\nusers: []\n"
    )
    result = subprocess.run(
        [
            str(commands / "bash"),
            str(_REPO_ROOT / "deployment/helm/dev/firecracker-ci.sh"),
            "verify",
        ],
        env={
            "PATH": str(commands),
            "KUBECONFIG": str(kubeconfig),
            "LC_ALL": "C",
            "TMPDIR": str(tmp_path),
            "CLI_LOG": str(log),
            "FIRECRACKER_PIN_HELPER": str(helper),
            "KIND_CLUSTER_NAME": "onyx-craft-ci",
            "KIND_NODE_NAME": "onyx-craft-ci-control-plane",
            "KATA_INSTALL_NODE_NAMES": "onyx-craft-ci-control-plane",
            "ONYX_FIRECRACKER_DEDICATED_HOST": "true",
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == (helper_exit or 42), result.stdout + result.stderr
    assert result.stdout == "PIN_HELPER_RECEIVED:verify\n"
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert not any(call[:2] == ["docker", "cp"] for call in calls)
    assert not any(call[0] == "kubectl" for call in calls)
    assert any(call[3:5] == ["bash", "-c"] for call in calls) == (helper_exit == 0)
