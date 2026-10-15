from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tarfile
from dataclasses import dataclass
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deployment/helm/dev/firecracker-ci.sh"
REVISION = "cb1076646aa3740577fafbf3d914198b7fe8e3f7"
ARCHIVE_SHA256 = "918e88fd393c28c89424e6535df0546ca36c1dfa7d8a5d685dee70b449380a9b"
ARCHIVE_URL = "https://github.com/containerd/containerd/releases/download/${CONTAINERD_VERSION}/containerd-${CONTAINERD_VERSION#v}-linux-amd64.tar.gz"
VERSION_OUTPUT = f"containerd github.com/containerd/containerd/v2 v2.1.1 {REVISION}"


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source)
    path.chmod(0o755)


def _docker_environment(tmp_path: Path, node_path: str) -> dict[str, str]:
    bash = shutil.which("bash")
    assert bash is not None
    _write_executable(
        tmp_path / "docker",
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
        "    environment = os.environ.copy()\n"
        "    environment['PATH'] = environment['ONYX_TEST_NODE_PATH']\n"
        "    for index, argument in enumerate(arguments[:-1]):\n"
        "        if argument == '-e':\n"
        "            name, value = arguments[index + 1].split('=', 1)\n"
        "            environment[name] = value\n"
        "    result = subprocess.run(\n"
        "        [os.environ['ONYX_TEST_BASH'], '-s'],\n"
        "        input=script,\n"
        "        text=True,\n"
        "        env=environment,\n"
        "        check=False,\n"
        "    )\n"
        "    sys.exit(result.returncode)\n"
        "sys.exit(2)\n",
    )
    return os.environ | {
        "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        "KIND_CLUSTER_NAME": "onyx-craft-ci",
        "KIND_NODE_NAME": "onyx-craft-ci-control-plane",
        "ONYX_TEST_BASH": bash,
        "ONYX_TEST_NODE_PATH": node_path,
    }


def test_node_setup_runs_and_propagates_its_failure(tmp_path: Path) -> None:
    node_bin = tmp_path / "node-bin"
    node_bin.mkdir()
    environment = _docker_environment(tmp_path, str(node_bin))
    result = subprocess.run(
        [environment["ONYX_TEST_BASH"], str(SCRIPT), "configure-kind-node"],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert result.stderr == "::error::dmsetup is required inside the kind node\n"


@dataclass(frozen=True)
class NodeSetup:
    script: Path
    environment: dict[str, str]
    daemon: Path
    config: Path
    data_dir: Path
    calls: Path
    candidate: bytes
    original_daemon: bytes
    original_config: bytes

    def run(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                self.environment["ONYX_TEST_BASH"],
                str(self.script),
                "configure-kind-node",
            ],
            env=self.environment,
            text=True,
            capture_output=True,
            check=False,
        )


def _daemon_source(revision: str, label: str) -> str:
    return (
        f"#!{shutil.which('bash')}\n"
        f"# {label}\n"
        'case "$0" in\n'
        '  "${ONYX_TEST_EXECUTABLE_DIR}/"*) ;;\n'
        "  *) exit 126 ;;\n"
        "esac\n"
        'case "$1" in\n'
        f'  --version) echo "containerd github.com/containerd/containerd/v2 v2.1.1 {revision}" ;;\n'
        '  config) echo "version = 3" ;;\n'
        "  *) exit 2 ;;\n"
        "esac\n"
    )


def _node_setup(
    tmp_path: Path,
    *,
    revision: str = REVISION,
    installed_revision: str = REVISION,
    bad_checksum: bool = False,
    candidate_bytes: bytes | None = None,
) -> NodeSetup:
    daemon_dir = tmp_path / "node/usr/local/bin"
    daemon_dir.mkdir(parents=True)
    daemon = daemon_dir / "containerd"
    _write_executable(daemon, _daemon_source(installed_revision, "original daemon"))
    for name in ("ctr", "containerd-shim-runc-v2", ".onyx-containerd.keep"):
        (daemon_dir / name).write_text(f"preserve {name}\n")
    config = tmp_path / "node/etc/containerd/config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('version = 3\nimports = ["/opt/kata/config.toml"]\n')
    data_dir = tmp_path / "node/data"
    devices = tmp_path / "node/dev"
    devices.mkdir()
    for name in ("kvm", "vhost-vsock"):
        (devices / name).touch()

    release = tmp_path / "release"
    release.mkdir()
    candidate = release / "containerd"
    _write_executable(candidate, _daemon_source(revision, "official fixture daemon"))
    if candidate_bytes is not None:
        candidate.write_bytes(candidate_bytes)
    candidate.chmod(0o700)
    archive = tmp_path / "containerd.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(candidate, arcname="bin/containerd")
        for name in ("ctr", "containerd-shim-runc-v2"):
            (release / name).write_text(f"do not install archive {name}\n")
            tar.add(release / name, arcname=f"bin/{name}")
    checksum = (
        "0" * 64 if bad_checksum else hashlib.sha256(archive.read_bytes()).hexdigest()
    )

    calls = tmp_path / "calls"
    calls.touch()
    node_bin = tmp_path / "node-bin"
    node_bin.mkdir()
    double = (
        f"#!{sys.executable}\n"
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        "name = Path(sys.argv[0]).name\n"
        "arguments = sys.argv[1:]\n"
        "with Path(os.environ['ONYX_TEST_CALLS']).open('a') as output:\n"
        "    output.write(' '.join([name, *arguments]) + '\\n')\n"
        "if name == 'dmsetup' and arguments[0] == 'info':\n"
        "    sys.exit(0 if os.environ.get('ONYX_TEST_POOL_EXISTS') == '1' else 1)\n"
        "if name == 'losetup':\n"
        "    print('/dev/loop10' if arguments[-1].endswith('/data') else '/dev/loop11')\n"
        "if name == 'blockdev':\n"
        "    print('4096')\n"
        "if name == 'ctr':\n"
        "    print('io.containerd.snapshotter.v1 devmapper linux/amd64 ' +\n"
        "          os.environ.get('ONYX_TEST_PLUGIN_STATUS', 'ok'))\n"
    )
    for name in ("dmsetup", "losetup", "blockdev", "systemctl", "modprobe", "ctr"):
        _write_executable(node_bin / name, double)
    environment = _docker_environment(
        tmp_path, os.pathsep.join((str(node_bin), str(daemon_dir), os.environ["PATH"]))
    ) | {
        "DEVMAPPER_POOL_NAME": "kata_ci_devpool",
        "DEVMAPPER_DATA_DIR": str(data_dir),
        "DEVMAPPER_DATA_SIZE": "4K",
        "DEVMAPPER_META_SIZE": "4K",
        "DEVMAPPER_BASE_IMAGE_SIZE": "4GB",
        "ONYX_TEST_CALLS": str(calls),
        "ONYX_TEST_EXECUTABLE_DIR": str(daemon_dir),
        "TMPDIR": str(tmp_path),
    }
    source = SCRIPT.read_text()
    assert ARCHIVE_SHA256 in source
    assert ARCHIVE_URL in source
    fixture_source = (
        source.replace("/usr/local/bin", str(daemon_dir))
        .replace("/etc/containerd/config.toml", str(config))
        .replace("/dev/kvm", str(devices / "kvm"))
        .replace("/dev/vhost-vsock", str(devices / "vhost-vsock"))
        .replace(ARCHIVE_SHA256, checksum)
        .replace(ARCHIVE_URL, archive.as_uri())
    )
    script = tmp_path / "fixture-ci.sh"
    script.write_text(fixture_source)
    return NodeSetup(
        script,
        environment,
        daemon,
        config,
        data_dir,
        calls,
        candidate.read_bytes(),
        daemon.read_bytes(),
        config.read_bytes(),
    )


def _assert_staging_cleanup(node: NodeSetup) -> None:
    assert sorted(path.name for path in node.daemon.parent.iterdir()) == [
        ".onyx-containerd.keep",
        "containerd",
        "containerd-shim-runc-v2",
        "ctr",
    ]
    for name in ("ctr", "containerd-shim-runc-v2", ".onyx-containerd.keep"):
        assert (node.daemon.parent / name).read_text() == f"preserve {name}\n"


def _assert_no_install_or_storage_mutation(node: NodeSetup) -> None:
    assert node.daemon.read_bytes() == node.original_daemon
    assert node.config.read_bytes() == node.original_config
    assert node.calls.read_text().splitlines() == [
        "modprobe dm_thin_pool",
        "modprobe loop",
        "dmsetup info kata_ci_devpool",
    ]
    _assert_staging_cleanup(node)


def test_node_setup_installs_verified_daemon_atomically(tmp_path: Path) -> None:
    node = _node_setup(tmp_path)

    with node.daemon.open("rb") as original:
        result = node.run()
        assert result.returncode == 0, result.stdout + result.stderr
        assert node.daemon.read_bytes() == node.candidate
        assert original.read() == node.original_daemon
    assert stat.S_IMODE(node.daemon.stat().st_mode) == 0o755
    assert node.config.read_text() == (
        'version = 3\nimports = ["/opt/kata/config.toml"]\n\n'
        "# BEGIN ONYX KATA FIRECRACKER CI DEVMAPPER\n"
        '[plugins."io.containerd.snapshotter.v1.devmapper"]\n'
        '  pool_name = "kata_ci_devpool"\n'
        f'  root_path = "{node.data_dir}"\n'
        '  base_image_size = "4GB"\n'
        "  discard_blocks = true\n"
        "# END ONYX KATA FIRECRACKER CI DEVMAPPER\n"
    )
    assert (node.data_dir / "data").stat().st_size == 4096
    assert (node.data_dir / "metadata").stat().st_size == 4096
    assert node.calls.read_text().splitlines()[-2:] == [
        "systemctl restart containerd",
        "ctr plugins ls",
    ]
    _assert_staging_cleanup(node)


@pytest.mark.parametrize("failure", ["checksum", "revision"])
def test_node_setup_rejects_archive_before_mutation(
    tmp_path: Path, failure: str
) -> None:
    node = _node_setup(
        tmp_path,
        revision="wrong-revision" if failure == "revision" else REVISION,
        bad_checksum=failure == "checksum",
    )

    result = node.run()

    assert result.returncode == 1, result.stdout + result.stderr
    if failure == "checksum":
        assert "FAILED" in result.stdout
    else:
        assert "wrong-revision" in result.stderr
        assert VERSION_OUTPUT in result.stderr
    _assert_no_install_or_storage_mutation(node)
    assert not node.data_dir.exists()


def test_node_setup_rejects_installed_revision_before_mutation(tmp_path: Path) -> None:
    node = _node_setup(tmp_path, installed_revision="wrong-installed-revision")

    result = node.run()

    assert result.returncode == 1, result.stdout + result.stderr
    assert "wrong-installed-revision" in result.stderr
    assert VERSION_OUTPUT in result.stderr
    assert node.daemon.read_bytes() == node.original_daemon
    assert node.config.read_bytes() == node.original_config
    assert node.calls.read_text() == ""
    assert not node.data_dir.exists()
    _assert_staging_cleanup(node)


def test_node_setup_rejects_unexecutable_daemon_before_mutation(tmp_path: Path) -> None:
    node = _node_setup(tmp_path, candidate_bytes=b"\x7fELF" + b"\0" * 60)

    result = node.run()

    assert result.returncode == 126, result.stdout + result.stderr
    assert "cannot execute binary file" in result.stderr
    _assert_no_install_or_storage_mutation(node)
    assert not node.data_dir.exists()


@pytest.mark.parametrize("existing", ["pool", "data", "metadata"])
def test_node_setup_refuses_existing_storage_before_install(
    tmp_path: Path, existing: str
) -> None:
    node = _node_setup(tmp_path)
    if existing == "pool":
        node.environment["ONYX_TEST_POOL_EXISTS"] = "1"
    else:
        node.data_dir.mkdir()
        (node.data_dir / existing).write_text("preserve backing file\n")

    result = node.run()

    assert result.returncode == 1, result.stdout + result.stderr
    assert "refusing to" in result.stderr
    _assert_no_install_or_storage_mutation(node)
    if existing == "pool":
        assert not node.data_dir.exists()
    else:
        assert sorted(path.name for path in node.data_dir.iterdir()) == [existing]
        assert (node.data_dir / existing).read_text() == "preserve backing file\n"


def test_node_setup_fails_when_devmapper_plugin_is_not_ok(tmp_path: Path) -> None:
    node = _node_setup(tmp_path)
    node.environment["ONYX_TEST_PLUGIN_STATUS"] = "error"

    result = node.run()

    assert result.returncode == 1, result.stdout + result.stderr
    assert node.daemon.read_bytes() == node.candidate
    assert (
        '[plugins."io.containerd.snapshotter.v1.devmapper"]' in node.config.read_text()
    )
    assert node.calls.read_text().splitlines()[-2:] == [
        "systemctl restart containerd",
        "ctr plugins ls",
    ]
    _assert_staging_cleanup(node)
