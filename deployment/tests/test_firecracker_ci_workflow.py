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
import yaml

SCRIPT = Path(__file__).resolve().parents[2] / "deployment/helm/dev/firecracker-ci.sh"
WORKFLOW = SCRIPT.parents[3] / ".github/workflows/pr-craft-k8s-tests.yml"
REVISION = "cb1076646aa3740577fafbf3d914198b7fe8e3f7"
ARCHIVE_SHA256 = "918e88fd393c28c89424e6535df0546ca36c1dfa7d8a5d685dee70b449380a9b"
ARCHIVE_URL = "https://github.com/containerd/containerd/releases/download/${CONTAINERD_VERSION}/containerd-${CONTAINERD_VERSION#v}-linux-amd64.tar.gz"
VERSION_OUTPUT = f"containerd github.com/containerd/containerd/v2 v2.1.1 {REVISION}"
INFRA_COMMANDS = (
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
    "sudo",
    "systemctl",
    "umount",
    "wget",
)


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source)
    path.chmod(0o755)


def _command_directory(path: Path, tools: tuple[str, ...]) -> None:
    path.mkdir(exist_ok=True)
    for name in tools:
        executable = shutil.which(name)
        assert executable is not None, f"required fixture tool {name} is missing"
        (path / name).symlink_to(executable)
    for name in INFRA_COMMANDS:
        _write_executable(
            path / name,
            f"#!{sys.executable}\n"
            "import sys\n"
            f"print('fixture refuses {name}', file=sys.stderr)\n"
            "sys.exit(99)\n",
        )


def _docker_environment(tmp_path: Path, node_path: str) -> dict[str, str]:
    bash = shutil.which("bash")
    assert bash is not None
    host_bin = tmp_path / "host-bin"
    _command_directory(
        host_bin, ("awk", "bash", "cat", "dirname", "grep", "mktemp", "sha256sum")
    )
    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.write_text(
        "apiVersion: v1\nkind: Config\nclusters: []\ncontexts: []\nusers: []\n"
    )
    _write_executable(
        host_bin / "docker",
        f"#!{sys.executable}\n"
        "import os\n"
        "import subprocess\n"
        "import sys\n"
        "\n"
        "arguments = sys.argv[1:]\n"
        "if arguments[0] == 'inspect':\n"
        "    if '-f' in arguments:\n"
        "        if '.Mounts' in arguments[2]:\n"
        "            print(os.environ.get('ONYX_TEST_DEV_BIND', 'bind /dev true rprivate'))\n"
        "        elif 'io.x-k8s.kind.role' in arguments[2]:\n"
        "            print('control-plane')\n"
        "        else:\n"
        "            print('onyx-craft-ci')\n"
        "    sys.exit(0)\n"
        "if arguments[0] == 'exec':\n"
        "    script = sys.stdin.read() if '-i' in arguments else ''\n"
        "    environment = os.environ.copy()\n"
        "    environment['ONYX_TEST_IN_NODE'] = '1'\n"
        "    environment['PATH'] = environment['ONYX_TEST_NODE_PATH']\n"
        "    for index, argument in enumerate(arguments[:-1]):\n"
        "        if argument == '-e':\n"
        "            name, value = arguments[index + 1].split('=', 1)\n"
        "            environment[name] = value\n"
        "    node_index = arguments.index(os.environ['KIND_NODE_NAME'])\n"
        "    command = arguments[node_index + 1:]\n"
        "    if command[0] == 'bash':\n"
        "        command[0] = os.environ['ONYX_TEST_BASH']\n"
        "    result = subprocess.run(\n"
        "        command,\n"
        "        input=script,\n"
        "        text=True,\n"
        "        env=environment,\n"
        "        check=False,\n"
        "    )\n"
        "    sys.exit(result.returncode)\n"
        "sys.exit(2)\n",
    )
    _write_executable(
        host_bin / "findmnt",
        f"#!{sys.executable}\n"
        "import os\n"
        "print(os.environ.get('ONYX_TEST_HOST_FSTYPE', 'devtmpfs'))\n",
    )
    return {
        "PATH": str(host_bin),
        "KUBECONFIG": str(kubeconfig),
        "LC_ALL": "C",
        "TMPDIR": str(tmp_path),
        "KIND_CLUSTER_NAME": "onyx-craft-ci",
        "KIND_NODE_NAME": "onyx-craft-ci-control-plane",
        "ONYX_FIRECRACKER_DEDICATED_HOST": "true",
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

    def run(
        self, command: str = "configure-kind-node"
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                self.environment["ONYX_TEST_BASH"],
                str(self.script),
                command,
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
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    (snapshots / "keep-existing").write_text("unowned snapshot\n")
    sysfs = tmp_path / "sys/dev/block/252:1"
    sysfs.mkdir(parents=True)
    (sysfs / "uevent").write_text("MAJOR=252\nMINOR=1\nDEVNAME=dm-1\nDEVTYPE=disk\n")
    (tmp_path / "uuid").write_text("00000000-0000-4000-8000-000000000001\n")
    pin_helper = tmp_path / "pin-helper.sh"
    pin_helper.write_text("set -euo pipefail\nexit 0\n")

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
    _command_directory(
        node_bin,
        (
            "awk",
            "bash",
            "cat",
            "grep",
            "install",
            "jq",
            "mkdir",
            "mktemp",
            "mv",
            "rm",
            "sed",
            "sha256sum",
            "tar",
            "test",
            "truncate",
        ),
    )
    double = (
        f"#!{sys.executable}\n"
        "import json\n"
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
        "devices = mapper_dir.parent\n"
        "snapshots = Path(os.environ['ONYX_TEST_SNAPSHOTS'])\n"
        "if name == 'findmnt':\n"
        "    print(os.environ.get('ONYX_TEST_NODE_FSTYPE', 'devtmpfs'))\n"
        "if name == 'stat':\n"
        "    side = 'NODE' if os.environ.get('ONYX_TEST_IN_NODE') else 'HOST'\n"
        "    print(os.environ.get('ONYX_TEST_' + side + '_RDEV', 'fc:1'))\n"
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
        "    side = 'NODE' if os.environ.get('ONYX_TEST_IN_NODE') else 'HOST'\n"
        "    print(os.environ.get('ONYX_TEST_' + side + '_SIZE', '4096'))\n"
        "if name == 'ctr':\n"
        "    if arguments == ['plugins', 'ls']:\n"
        "        status = os.environ.get('ONYX_TEST_PLUGIN_STATUS', 'ok')\n"
        "        if not (mapper_dir / 'kata_ci_devpool').is_file():\n"
        "            status = 'error'\n"
        "        print('io.containerd.snapshotter.v1 devmapper linux/amd64 ' + status)\n"
        "    elif arguments[:2] == ['--namespace', 'k8s.io']:\n"
        "        assert arguments[2:5] == ['snapshots', '--snapshotter', 'devmapper']\n"
        "        action = arguments[5]\n"
        "        if action == 'list':\n"
        "            if os.environ.get('ONYX_TEST_SNAPSHOT_LIST_FAIL'):\n"
        "                sys.exit(31)\n"
        "            print('KEY PARENT KIND')\n"
        "            for snapshot in snapshots.iterdir():\n"
        "                print(snapshot.name + ' Active')\n"
        "        elif action == 'prepare':\n"
        "            assert arguments[6] == '--mounts'\n"
        "            key = arguments[7]\n"
        "            if (snapshots / key).exists() or os.environ.get('ONYX_TEST_SNAPSHOT_PREPARE_FAIL'):\n"
        "                sys.exit(32)\n"
        "            (snapshots / key).write_text('owned snapshot\\n')\n"
        "            source = mapper_dir / 'kata_ci_devpool-snap-1'\n"
        "            source.touch()\n"
        "            if not os.environ.get('ONYX_TEST_MISSING_CANONICAL'):\n"
        "                (devices / 'dm-1').touch()\n"
        "            mounts = [{'Type': 'ext4', 'Source': str(source), 'Options': ['rw']}]\n"
        "            print('invalid' if os.environ.get('ONYX_TEST_BAD_MOUNTS') else json.dumps(mounts, indent=4))\n"
        "        elif action == 'remove':\n"
        "            if os.environ.get('ONYX_TEST_SNAPSHOT_REMOVE_FAIL'):\n"
        "                sys.exit(33)\n"
        "            (snapshots / arguments[6]).unlink()\n"
        "            (mapper_dir / 'kata_ci_devpool-snap-1').unlink()\n"
        "            (devices / 'dm-1').unlink(missing_ok=True)\n"
        "        else:\n"
        "            raise AssertionError(arguments)\n"
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
    for name in (
        "dmsetup",
        "losetup",
        "blockdev",
        "systemctl",
        "modprobe",
        "ctr",
        "findmnt",
        "stat",
    ):
        _write_executable(node_bin / name, double)
    _write_executable(
        node_bin / "curl",
        f"#!{sys.executable}\n"
        "import os\nimport sys\nfrom pathlib import Path\n"
        "arguments = sys.argv[1:]\n"
        "archive = Path(os.environ['ONYX_TEST_ARCHIVE'])\n"
        "assert arguments == ['--fail', '--location', '--silent', '--show-error',\n"
        "                     '--retry', '5', '--retry-delay', '2', '--retry-all-errors',\n"
        "                     '--output', arguments[-2], archive.as_uri()]\n"
        "destination = Path(arguments[-2])\n"
        "assert destination.parent.parent == Path(os.environ['ONYX_TEST_EXECUTABLE_DIR'])\n"
        "destination.write_bytes(archive.read_bytes())\n",
    )
    environment = _docker_environment(
        tmp_path, os.pathsep.join((str(daemon_dir), str(node_bin)))
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
        "ONYX_TEST_SNAPSHOTS": str(snapshots),
        "ONYX_TEST_ARCHIVE": str(archive),
        "FIRECRACKER_PIN_HELPER": str(pin_helper),
        "TMPDIR": str(tmp_path),
    }
    environment.pop("DM_DISABLE_UDEV", None)
    host_bin = tmp_path / "host-bin"
    for name in ("stat", "blockdev"):
        _write_executable(host_bin / name, double)
    _write_executable(
        host_bin / "sudo",
        f"#!{sys.executable}\n"
        "import os\nimport sys\n"
        "assert sys.argv[1:4] == ['-n', 'blockdev', '--getsize64']\n"
        "assert len(sys.argv) == 5\n"
        "assert sys.argv[4] == os.environ['ONYX_TEST_MAPPER_DIR'].removesuffix('/mapper') + '/dm-1'\n"
        "os.execvp(sys.argv[2], sys.argv[2:])\n",
    )
    _write_executable(
        host_bin / "kubectl",
        f"#!{sys.executable}\n"
        "import os\nimport sys\nfrom pathlib import Path\n"
        "arguments = sys.argv[1:]\n"
        "with Path(os.environ['ONYX_TEST_CALLS']).open('a') as output:\n"
        "    output.write('kubectl ' + ' '.join(arguments) + '\\n')\n"
        "if '--' in arguments:\n"
        "    print(os.environ.get('ONYX_TEST_GUEST_BOOT_ID', 'guest-boot-id'))\n"
        "elif 'jsonpath={.spec.nodeName}' in arguments:\n"
        "    print('onyx-craft-ci-control-plane')\n"
        "elif 'jsonpath={.status.nodeInfo.bootID}' in arguments:\n"
        "    print(os.environ.get('ONYX_TEST_NODE_BOOT_ID', 'node-boot-id'))\n"
        "elif any('.spec.runtimeClassName' in argument or '.handler' in argument for argument in arguments):\n"
        "    print('kata-fc')\n",
    )
    source = SCRIPT.read_text()
    assert ARCHIVE_SHA256 in source
    assert ARCHIVE_URL in source
    fixture_source = (
        source.replace("/usr/local/bin", str(daemon_dir))
        .replace("/etc/containerd/config.toml", str(config))
        .replace("/dev/kvm", str(devices / "kvm"))
        .replace("/dev/vhost-vsock", str(devices / "vhost-vsock"))
        .replace("/dev/mapper/", f"{mapper_dir}/")
        .replace('"/dev/${devname}"', f'"{devices}/${{devname}}"')
        .replace("/sys/dev/block/", f"{tmp_path}/sys/dev/block/")
        .replace("/proc/sys/kernel/random/uuid", str(tmp_path / "uuid"))
        .replace("/etc/systemd/system/containerd.service.d", str(service_dir))
        .replace('[ ! -b "${pool_path}" ]', '[ ! -f "${pool_path}" ]')
        .replace('test -b "${snapshot_source}"', 'test -f "${snapshot_source}"')
        .replace('test -b "${canonical_path}"', 'test -f "${canonical_path}"')
        .replace('[ ! -b "${canonical_path}" ]', '[ ! -f "${canonical_path}" ]')
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
        "findmnt --noheadings --output FSTYPE --target /dev",
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
    assert (
        node.calls.read_text() == "findmnt --noheadings --output FSTYPE --target /dev\n"
    )
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


def test_ci_kind_config_shares_only_the_dedicated_host_devices(tmp_path: Path) -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    jobs = workflow["jobs"]
    job = next(job for job in jobs.values() if "Write kind config" in str(job))
    step = next(
        step for step in job["steps"] if step.get("name") == "Write kind config"
    )
    environment = _docker_environment(tmp_path, "")

    result = subprocess.run(
        [environment["ONYX_TEST_BASH"], "-euo", "pipefail", "-c", step["run"]],
        env=environment | {"RUNNER_TEMP": str(tmp_path)},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    config = yaml.safe_load((tmp_path / "kind-config.yaml").read_text())
    assert config["nodes"] == [
        {
            "role": "control-plane",
            "extraMounts": [
                {
                    "hostPath": "/dev",
                    "containerPath": "/dev",
                    "readOnly": False,
                    "propagation": "None",
                },
                {
                    "hostPath": "/lib/modules",
                    "containerPath": "/lib/modules",
                    "readOnly": True,
                },
            ],
        }
    ]
    assert config["networking"] == {
        "disableDefaultCNI": True,
        "podSubnet": "192.168.0.0/16",
    }
    assert job["env"]["ONYX_FIRECRACKER_DEDICATED_HOST"] == "true"
    assert all(
        "ONYX_FIRECRACKER_DEDICATED_HOST" not in other.get("env", {})
        for other in jobs.values()
        if other is not job
    )


@pytest.mark.parametrize(
    "command",
    ["preflight-host", "configure-kind-node", "install-kata", "verify", "all"],
)
@pytest.mark.parametrize("acknowledgement", [None, "false", "1"])
def test_public_setup_requires_explicit_dedicated_host(
    tmp_path: Path, command: str, acknowledgement: str | None
) -> None:
    node = _node_setup(tmp_path)
    if acknowledgement is None:
        node.environment.pop("ONYX_FIRECRACKER_DEDICATED_HOST")
    else:
        node.environment["ONYX_FIRECRACKER_DEDICATED_HOST"] = acknowledgement

    result = node.run(command)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "ONYX_FIRECRACKER_DEDICATED_HOST=true" in result.stderr
    assert node.calls.read_text() == ""
    assert node.daemon.read_bytes() == node.original_daemon
    assert not node.data_dir.exists()
    assert not node.service_dropin.exists()


@pytest.mark.parametrize("side", ["HOST", "NODE"])
def test_node_setup_rejects_private_device_filesystem_before_mutation(
    tmp_path: Path, side: str
) -> None:
    node = _node_setup(tmp_path)
    node.environment[f"ONYX_TEST_{side}_FSTYPE"] = "tmpfs"

    result = node.run()

    assert result.returncode == 1, result.stdout + result.stderr
    assert "/dev must use devtmpfs" in result.stderr
    assert node.daemon.read_bytes() == node.original_daemon
    assert node.config.read_bytes() == node.original_config
    assert not node.data_dir.exists()
    assert not node.service_dropin.exists()
    assert all(
        call.startswith("findmnt ") for call in node.calls.read_text().splitlines()
    )


@pytest.mark.parametrize(
    "bind",
    [
        "",
        "bind /dev false rprivate",
        "bind /dev true rshared",
        "bind /private-dev true rprivate",
    ],
)
def test_node_setup_rejects_wrong_device_bind_before_mutation(
    tmp_path: Path, bind: str
) -> None:
    node = _node_setup(tmp_path)
    node.environment["ONYX_TEST_DEV_BIND"] = bind

    result = node.run()

    assert result.returncode == 1, result.stdout + result.stderr
    assert (
        "writable /dev bind from host /dev with rprivate propagation" in result.stderr
    )
    assert node.calls.read_text() == ""
    assert node.daemon.read_bytes() == node.original_daemon
    assert not node.data_dir.exists()


def _snapshot_calls(node: NodeSetup) -> list[str]:
    return [
        call
        for call in node.calls.read_text().splitlines()
        if call.startswith("ctr --namespace k8s.io snapshots --snapshotter devmapper ")
    ]


def test_verify_checks_new_canonical_device_and_removes_only_its_snapshot(
    tmp_path: Path,
) -> None:
    node = _node_setup(tmp_path)
    assert node.run().returncode == 0

    result = node.run("verify")

    assert result.returncode == 0, result.stdout + result.stderr
    key = "onyx-devmapper-probe-00000000-0000-4000-8000-000000000001"
    prefix = "ctr --namespace k8s.io snapshots --snapshotter devmapper"
    assert _snapshot_calls(node) == [
        f"{prefix} list",
        f"{prefix} prepare --mounts {key}",
        f"{prefix} remove {key}",
    ]
    assert sorted(path.name for path in (tmp_path / "snapshots").iterdir()) == [
        "keep-existing"
    ]
    assert (tmp_path / "snapshots/keep-existing").read_text() == "unowned snapshot\n"
    assert (node.mappings / "kata_ci_devpool").read_text() == "DM_DISABLE_UDEV=1\n"
    assert (node.data_dir / "data").stat().st_size == 4096
    assert (
        f"canonical={node.mapper_dir.parent}/dm-1 rdev=fc:1 bytes=4096" in result.stdout
    )
    assert "io.containerd.snapshotter.v1 devmapper linux/amd64 ok" in result.stdout
    assert "node=node-boot-id guest=guest-boot-id" in result.stdout
    calls = node.calls.read_text().splitlines()
    assert calls.index(f"{prefix} remove {key}") < next(
        index for index, call in enumerate(calls) if call.startswith("kubectl ")
    )


@pytest.mark.parametrize(
    ("setting", "message"),
    [
        ("MISSING_CANONICAL", "canonical devmapper device"),
        ("BAD_MOUNTS", "parse error"),
        ("HOST_RDEV", "device identity"),
        ("NODE_SIZE", "device size"),
    ],
)
def test_verify_cleans_owned_snapshot_after_device_validation_failure(
    tmp_path: Path, setting: str, message: str
) -> None:
    node = _node_setup(tmp_path)
    assert node.run().returncode == 0
    node.environment[f"ONYX_TEST_{setting}"] = {
        "HOST_RDEV": "fc:2",
        "NODE_SIZE": "0",
    }.get(setting, "1")

    result = node.run("verify")

    assert result.returncode != 0, result.stdout + result.stderr
    assert message in result.stderr
    assert " prepare --mounts " in _snapshot_calls(node)[1]
    assert " remove onyx-devmapper-probe-" in _snapshot_calls(node)[2]
    assert sorted(path.name for path in (tmp_path / "snapshots").iterdir()) == [
        "keep-existing"
    ]
    assert not any(
        call.startswith("kubectl ") for call in node.calls.read_text().splitlines()
    )


@pytest.mark.parametrize("failure", ["existing", "list", "prepare"])
def test_verify_never_removes_a_snapshot_it_did_not_create(
    tmp_path: Path, failure: str
) -> None:
    node = _node_setup(tmp_path)
    assert node.run().returncode == 0
    key = "onyx-devmapper-probe-00000000-0000-4000-8000-000000000001"
    if failure == "existing":
        (tmp_path / "snapshots" / key).write_text("existing probe name\n")
    else:
        node.environment[f"ONYX_TEST_SNAPSHOT_{failure.upper()}_FAIL"] = "1"

    result = node.run("verify")

    assert result.returncode != 0, result.stdout + result.stderr
    assert not any(" remove " in call for call in _snapshot_calls(node))
    assert not any(
        call.startswith("kubectl ") for call in node.calls.read_text().splitlines()
    )
    assert (tmp_path / "snapshots/keep-existing").read_text() == "unowned snapshot\n"
    if failure == "existing":
        assert "already exists; refusing" in result.stderr
        assert (tmp_path / "snapshots" / key).read_text() == "existing probe name\n"


def test_verify_reports_owned_snapshot_cleanup_failure(tmp_path: Path) -> None:
    node = _node_setup(tmp_path)
    assert node.run().returncode == 0
    node.environment["ONYX_TEST_SNAPSHOT_REMOVE_FAIL"] = "1"

    result = node.run("verify")

    assert result.returncode != 0, result.stdout + result.stderr
    assert "failed to remove owned devmapper probe" in result.stderr
    assert not any(
        call.startswith("kubectl ") for call in node.calls.read_text().splitlines()
    )


@pytest.mark.parametrize(
    ("node_boot", "guest_boot", "message"),
    [("", "guest", "failed to read"), ("same", "same", "matches")],
)
def test_verify_preserves_boot_id_refusal(
    tmp_path: Path, node_boot: str, guest_boot: str, message: str
) -> None:
    node = _node_setup(tmp_path)
    assert node.run().returncode == 0
    node.environment["ONYX_TEST_NODE_BOOT_ID"] = node_boot
    node.environment["ONYX_TEST_GUEST_BOOT_ID"] = guest_boot

    result = node.run("verify")

    assert result.returncode == 1, result.stdout + result.stderr
    assert message in result.stderr
