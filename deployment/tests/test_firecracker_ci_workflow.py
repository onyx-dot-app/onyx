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
    service_dropin: Path
    service_environment: Path
    mappings: Path
    mapper_dir: Path
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
    mapper_dir = devices / "mapper"
    mapper_dir.mkdir()
    mappings = tmp_path / "kernel-mappings"
    mappings.mkdir()
    service_dir = tmp_path / "node/etc/systemd/system/containerd.service.d"
    service_dir.mkdir(parents=True)
    (service_dir / "10-preserve.conf").write_text("[Service]\nEnvironment=KEEP=1\n")
    service_dropin = service_dir / "20-onyx-devmapper.conf"
    service_environment = tmp_path / "service-environment"

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
        "import subprocess\n"
        "import sys\n"
        "from pathlib import Path\n"
        "name = Path(sys.argv[0]).name\n"
        "arguments = sys.argv[1:]\n"
        "with Path(os.environ['ONYX_TEST_CALLS']).open('a') as output:\n"
        "    output.write(' '.join([name, *arguments]) + '\\n')\n"
        "mapper_dir = Path(os.environ['ONYX_TEST_MAPPER_DIR'])\n"
        "mappings = Path(os.environ['ONYX_TEST_MAPPINGS'])\n"
        "service_environment = Path(os.environ['ONYX_TEST_SERVICE_ENVIRONMENT'])\n"
        "if name == 'dmsetup':\n"
        "    target = arguments[1]\n"
        "    mapping = mappings / Path(target).name\n"
        "    node = mapper_dir / Path(target).name\n"
        "    if arguments[0] == 'create':\n"
        "        setting = 'DM_DISABLE_UDEV=' + os.environ.get('DM_DISABLE_UDEV', '')\n"
        "        mapping.write_text(setting + '\\n')\n"
        "        if 'DM_DISABLE_UDEV' in os.environ and not os.environ.get('ONYX_TEST_MISSING_NODE'):\n"
        "            if os.environ.get('ONYX_TEST_NODE_KIND') == 'directory':\n"
        "                node.mkdir()\n"
        "            else:\n"
        "                node.touch()\n"
        "        sys.exit(0)\n"
        "    if arguments[0] == 'info':\n"
        "        exists = mapping.exists() or os.environ.get('ONYX_TEST_POOL_EXISTS') == '1'\n"
        "        lookup = 'path' if Path(target).is_absolute() else 'name'\n"
        "        exists = exists and (lookup == 'name' or node.exists())\n"
        "        if os.environ.get('ONYX_TEST_INFO_FAILURE') == lookup:\n"
        "            exists = False\n"
        "        if not exists:\n"
        "            print('Device ' + target + ' not found', file=sys.stderr)\n"
        "            sys.exit(1)\n"
        "        print('Name: ' + mapping.name + '\\nState: ACTIVE')\n"
        "    elif arguments[0] in ('table', 'status', 'deps'):\n"
        "        if not mapping.exists():\n"
        "            sys.exit(1)\n"
        "        print({'table': '0 8 thin-pool 7:11 7:10 128 32768',\n"
        "               'status': '0 8 thin-pool 0 1/8 1/8 - rw',\n"
        "               'deps': '2 dependencies : (7, 11) (7, 10)'}[arguments[0]])\n"
        "if name == 'systemctl':\n"
        "    loaded_environment = service_environment.with_suffix('.loaded')\n"
        "    if arguments == ['daemon-reload']:\n"
        "        dropin = Path(os.environ['ONYX_TEST_SERVICE_DROPIN']).read_text()\n"
        "        loaded_environment.write_text(''.join(\n"
        "            line.removeprefix('Environment=') + '\\n'\n"
        "            for line in dropin.splitlines() if line.startswith('Environment=')\n"
        "        ))\n"
        "    elif arguments == ['restart', 'containerd']:\n"
        "        service_environment.write_text(\n"
        "            loaded_environment.read_text() if loaded_environment.exists() else ''\n"
        "        )\n"
        "if name == 'losetup':\n"
        "    print('/dev/loop10' if arguments[-1].endswith('/data') else '/dev/loop11')\n"
        "if name == 'blockdev':\n"
        "    print('4096')\n"
        "if name == 'ctr':\n"
        "    if arguments == ['plugins', 'ls']:\n"
        "        status = os.environ.get('ONYX_TEST_PLUGIN_STATUS', 'ok')\n"
        "        if not (mapper_dir / 'kata_ci_devpool').is_file():\n"
        "            status = 'error'\n"
        "        print('io.containerd.snapshotter.v1 devmapper linux/amd64 ' + status)\n"
        "    elif arguments[:2] == ['snapshots', 'prepare']:\n"
        "        environment = os.environ.copy()\n"
        "        environment.pop('DM_DISABLE_UDEV', None)\n"
        "        for setting in service_environment.read_text().splitlines():\n"
        "            key, value = setting.split('=', 1)\n"
        "            environment[key] = value\n"
        "        subprocess.run(['dmsetup', 'create', arguments[2], '--table',\n"
        "                        '0 8 thin ' + str(mapper_dir / 'kata_ci_devpool') + ' 1'],\n"
        "                       env=environment, check=True)\n"
        "        sys.exit(subprocess.run(\n"
        "            ['dmsetup', 'info', str(mapper_dir / arguments[2])],\n"
        "            env=environment, check=False).returncode)\n"
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
        "ONYX_TEST_MAPPER_DIR": str(mapper_dir),
        "ONYX_TEST_MAPPINGS": str(mappings),
        "ONYX_TEST_SERVICE_DROPIN": str(service_dropin),
        "ONYX_TEST_SERVICE_ENVIRONMENT": str(service_environment),
        "TMPDIR": str(tmp_path),
    }
    environment.pop("DM_DISABLE_UDEV", None)
    source = SCRIPT.read_text()
    assert ARCHIVE_SHA256 in source
    assert ARCHIVE_URL in source
    fixture_source = (
        source.replace("/usr/local/bin", str(daemon_dir))
        .replace("/etc/containerd/config.toml", str(config))
        .replace("/dev/kvm", str(devices / "kvm"))
        .replace("/dev/vhost-vsock", str(devices / "vhost-vsock"))
        .replace("/dev/mapper/", f"{mapper_dir}/")
        .replace("/etc/systemd/system/containerd.service.d", str(service_dir))
        .replace('[ ! -b "${pool_path}" ]', '[ ! -f "${pool_path}" ]')
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
        service_dropin,
        service_environment,
        mappings,
        mapper_dir,
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
    assert not node.service_dropin.exists()
    assert not node.service_environment.exists()
    assert not node.service_environment.with_suffix(".loaded").exists()
    assert (node.service_dropin.parent / "10-preserve.conf").read_text() == (
        "[Service]\nEnvironment=KEEP=1\n"
    )
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
    assert (node.mappings / "kata_ci_devpool").read_text() == "DM_DISABLE_UDEV=1\n"
    assert (node.mapper_dir / "kata_ci_devpool").is_file()
    assert (
        node.service_dropin.read_text() == "[Service]\nEnvironment=DM_DISABLE_UDEV=1\n"
    )
    assert node.service_environment.read_text() == "DM_DISABLE_UDEV=1\n"
    assert (node.service_dropin.parent / "10-preserve.conf").read_text() == (
        "[Service]\nEnvironment=KEEP=1\n"
    )
    assert node.calls.read_text().splitlines()[-8:] == [
        "dmsetup info kata_ci_devpool",
        f"dmsetup info {node.mapper_dir}/kata_ci_devpool",
        "dmsetup table kata_ci_devpool",
        "dmsetup status kata_ci_devpool",
        "dmsetup deps kata_ci_devpool",
        "systemctl daemon-reload",
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
    assert not node.service_dropin.exists()
    assert not node.service_environment.exists()
    assert not node.service_environment.with_suffix(".loaded").exists()
    assert (node.service_dropin.parent / "10-preserve.conf").read_text() == (
        "[Service]\nEnvironment=KEEP=1\n"
    )
    assert node.calls.read_text() == ""
    assert not node.data_dir.exists()
    _assert_staging_cleanup(node)


def test_node_setup_service_passes_environment_to_later_thin_creation(
    tmp_path: Path,
) -> None:
    node = _node_setup(tmp_path)
    result = node.run()
    assert result.returncode == 0, result.stdout + result.stderr

    service_environment = node.environment | {
        "PATH": node.environment["ONYX_TEST_NODE_PATH"]
    }
    assert "DM_DISABLE_UDEV" not in service_environment
    result = subprocess.run(
        [str(tmp_path / "node-bin/systemctl"), "restart", "containerd"],
        env=service_environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    result = subprocess.run(
        [str(tmp_path / "node-bin/ctr"), "snapshots", "prepare", "kata_ci_thin"],
        env=service_environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (node.mappings / "kata_ci_thin").read_text() == "DM_DISABLE_UDEV=1\n"
    assert (node.mapper_dir / "kata_ci_thin").is_file()
    assert node.calls.read_text().splitlines()[-3:] == [
        "ctr snapshots prepare kata_ci_thin",
        f"dmsetup create kata_ci_thin --table 0 8 thin {node.mapper_dir}/kata_ci_devpool 1",
        f"dmsetup info {node.mapper_dir}/kata_ci_thin",
    ]


@pytest.mark.parametrize("failure", ["name", "path", "missing-node", "node-type"])
def test_node_setup_checks_created_pool_before_service_mutation(
    tmp_path: Path, failure: str
) -> None:
    node = _node_setup(tmp_path)
    if failure in ("name", "path"):
        node.environment["ONYX_TEST_INFO_FAILURE"] = failure
    elif failure == "missing-node":
        node.environment["ONYX_TEST_MISSING_NODE"] = "1"
    else:
        node.environment["ONYX_TEST_NODE_KIND"] = "directory"

    result = node.run()

    assert result.returncode == 1, result.stdout + result.stderr
    assert node.daemon.read_bytes() == node.candidate
    assert node.config.read_bytes() == node.original_config
    assert not node.service_dropin.exists()
    assert not node.service_environment.exists()
    assert not node.service_environment.with_suffix(".loaded").exists()
    assert (node.mappings / "kata_ci_devpool").read_text() == "DM_DISABLE_UDEV=1\n"
    if failure == "node-type":
        assert "is not a block device" in result.stderr
    else:
        assert "not found" in result.stderr
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
