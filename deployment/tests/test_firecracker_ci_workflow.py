from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "deployment/helm/dev/firecracker-ci.sh"


def test_node_setup_runs_and_propagates_its_failure(tmp_path: Path) -> None:
    bash = shutil.which("bash")
    assert bash is not None
    node_bin = tmp_path / "node-bin"
    node_bin.mkdir()
    docker = tmp_path / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        "import os\n"
        "import subprocess\n"
        "import sys\n"
        "\n"
        "arguments = sys.argv[1:]\n"
        "if arguments[0] == 'inspect':\n"
        "    if '-f' in arguments:\n"
        "        if 'io.x-k8s.kind.role' in arguments[2]:\n"
        "            print('control-plane')\n"
        "        else:\n"
        "            print('onyx-craft-ci')\n"
        "    sys.exit(0)\n"
        "if arguments[0] == 'exec':\n"
        "    script = sys.stdin.read() if '-i' in arguments else ''\n"
        "    result = subprocess.run(\n"
        "        [os.environ['ONYX_TEST_BASH'], '-s'],\n"
        "        input=script,\n"
        "        text=True,\n"
        "        env={'PATH': os.environ['ONYX_TEST_NODE_PATH']},\n"
        "        check=False,\n"
        "    )\n"
        "    sys.exit(result.returncode)\n"
        "sys.exit(2)\n"
    )
    docker.chmod(0o755)
    environment = os.environ | {
        "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        "KIND_CLUSTER_NAME": "onyx-craft-ci",
        "KIND_NODE_NAME": "onyx-craft-ci-control-plane",
        "ONYX_TEST_BASH": bash,
        "ONYX_TEST_NODE_PATH": str(node_bin),
    }

    result = subprocess.run(
        [bash, str(SCRIPT), "configure-kind-node"],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert result.stderr == "::error::dmsetup is required inside the kind node\n"
