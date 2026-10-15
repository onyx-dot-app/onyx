"""Real shell and Helm contracts. Command recorders do not prove VM behavior."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests.common.paths import find_ancestor_containing
from tests.external_dependency_unit.craft_helm.rendering import skip_or_fail

_REPO_ROOT = find_ancestor_containing("deployment/helm/dev")
_DEV_DIR = _REPO_ROOT / "deployment/helm/dev"
_RECORDER = r"""
import io
import json
import os
import sys
import tarfile
from pathlib import Path

tool = Path(sys.argv[0]).name
args = sys.argv[1:]
log = Path(os.environ["CLI_LOG"])
with log.open("a") as output:
    output.write(json.dumps([tool, *args]) + "\n")
case = os.environ.get("CLI_CASE", "ready")
if tool == "kind":
    if args[:2] == ["get", "clusters"] and case != "missing-cluster":
        print("test-dev")
    if args[:2] == ["get", "nodes"]:
        print("test-dev-control-plane")
        if case == "multi-node":
            print("test-dev-worker")
elif tool == "docker":
    if args[:1] == ["inspect"]:
        print("another-cluster" if case == "wrong-node-cluster" else "test-dev")
    elif args[:2] == ["image", "inspect"] and "--format" in args:
        print("linux/ppc64le" if case == "unsupported-guest-platform" else "linux/arm64")
    elif args[:2] == ["image", "save"]:
        if case == "failed-guest-save":
            print("guest image save failed", file=sys.stderr)
            sys.exit(1)
        config = "blobs/sha256/" + "a" * 64
        if case == "classic-guest-config":
            config = "a" * 64 + ".json"
        if case == "invalid-guest-config":
            config = "not-a-config-digest"
        manifests = [{"Config": config, "RepoTags": ["onyxdotapp/sandbox:dev"]}]
        if case == "ambiguous-guest-manifest":
            manifests *= 2
        payload = json.dumps(manifests).encode()
        with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as archive:
            member = tarfile.TarInfo("manifest.json")
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
    elif args[:1] == ["exec"]:
        if "-i" in args:
            payload = sys.stdin.buffer.read()
        if case == "missing-kvm":
            sys.exit(1)
        if "ctr" in args and "import" in args and case == "failed-guest-import":
            print("guest image import failed", file=sys.stderr)
            sys.exit(1)
        if "ctr" in args and "import" in args:
            with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
                stream = archive.extractfile("manifest.json")
                config = json.load(stream)[0]["Config"]
            with log.open("a") as output:
                output.write(json.dumps(["imported-guest-config", config]) + "\n")
        if "inspecti" in args:
            if case == "failed-guest-inspection":
                print("guest image inspection failed", file=sys.stderr)
                sys.exit(1)
            digest = "b" * 64 if case == "wrong-guest-image" else "a" * 64
            pinned = "false" if case == "unpinned-guest-image" else "true"
            print(f"sha256:{digest} {pinned}")
elif tool == "kubectl":
    assert args[:2] == ["--context", "kind-test-dev"], args
    if "get" in args:
        resource = args[args.index("get") + 1]
        if case == f"{resource}-api-error":
            print("API read failed", file=sys.stderr)
            sys.exit(1)
        if resource == "runtimeclass":
            print("runc" if case == "wrong-runtime" else "kata-fc")
        elif resource == "namespace":
            print("namespace/onyx-sandboxes")
        elif resource == "podtemplate":
            if case != "fresh":
                print("podtemplate/sandbox-pod")
        elif resource == "pods" and "onyx-sandboxes" in args:
            rolled = '"rollout", "status"' in log.read_text()
            applied = '"applied-template"' in log.read_text()
            if case == "pods-api-error-after-apply" and applied:
                print("API read failed", file=sys.stderr)
                sys.exit(1)
            if (
                case == "occupied"
                or case == "occupied-after-rollout" and rolled
                or case == "occupied-after-apply" and applied
            ):
                print("pod/sandbox-unsaved-work")
        elif resource == "pods":
            print("old-api\tonyxdotapp/onyx-backend:edge ")
            print("old-worker\tonyxdotapp/onyx-backend:edge ")
        elif resource == "deployments":
            if case != "fresh":
                print("onyx-api-server\tcontainers/api-server=onyxdotapp/onyx-backend:edge containers/traffic-agent=tel2:stable ")
                print("onyx-celery-worker-heavy\tcontainers/celery-worker-heavy=onyxdotapp/onyx-backend:edge ")
                print("onyx-celery-worker-scheduled-tasks\tcontainers/celery-worker-scheduled-tasks=onyxdotapp/onyx-backend:edge ")
                print("onyx-sandbox-proxy\tcontainers/sandbox-proxy=onyxdotapp/onyx-backend:edge initContainers/build-upstream-ca-bundle=onyxdotapp/onyx-backend:edge ")
                print("onyx-webserver\tcontainers/webserver=onyxdotapp/onyx-web-server:edge ")
    elif "rollout" in args and "status" in args and case == "failed-rollout":
        sys.exit(1)
    elif "wait" in args and case == "old-pod-remains":
        sys.exit(1)
    elif "apply" in args:
        with log.open("a") as output:
            output.write(json.dumps(["applied-template", Path(args[-1]).read_text()]) + "\n")
elif tool == "helm":
    if args[:2] == ["dependency", "update"] and case == "failed-dependencies":
        print("Helm dependency update failed", file=sys.stderr)
        sys.exit(1)
    if args[:1] == ["template"]:
        if case == "failed-render":
            sys.exit(1)
        print("kind: PodTemplate\nmetadata:\n  name: sandbox-pod")
"""


def _run_script(
    tmp_path: Path,
    script: str,
    *args: str,
    case: str = "ready",
    dev_dir: Path = _DEV_DIR,
) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    command_dir = tmp_path / "bin"
    command_dir.mkdir()
    recorder = command_dir / "recorder"
    recorder.write_text(f"#!{sys.executable}\n{_RECORDER}")
    recorder.chmod(0o755)
    for tool in ("docker", "kind", "kubectl", "helm", "telepresence"):
        (command_dir / tool).symlink_to(recorder)
    log = tmp_path / "commands.jsonl"
    env = {
        **os.environ,
        "PATH": f"{command_dir}:{os.environ['PATH']}",
        "CLI_LOG": str(log),
        "CLI_CASE": case,
        "CLUSTER_NAME": "test-dev",
        "NAMESPACE": "onyx",
    }
    result = subprocess.run(
        ["bash", str(dev_dir / script), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    commands: list[list[str]] = (
        [json.loads(line) for line in log.read_text().splitlines()]
        if log.exists()
        else []
    )
    return result, commands


@pytest.mark.parametrize("case", ["missing-cluster", "wrong-runtime", "missing-kvm"])
@pytest.mark.parametrize("script", ["k8s-up.sh", "craft-up.sh", "refresh-images.sh"])
def test_missing_runtime_stops_before_changes(
    tmp_path: Path, case: str, script: str
) -> None:
    args = ("--cluster-name", "test-dev") if script != "refresh-images.sh" else ()
    result, commands = _run_script(tmp_path, script, *args, case=case)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Craft requires" in result.stderr or "needs usable KVM" in result.stderr
    assert commands
    assert all(
        command[0] == "kind"
        and command[1] == "get"
        or command[0] == "kubectl"
        and "get" in command
        or command[0] == "docker"
        and command[1] == "exec"
        for command in commands
    ), commands


def test_non_craft_cluster_only_path_does_not_need_runtime(tmp_path: Path) -> None:
    result, commands = _run_script(
        tmp_path,
        "craft-up.sh",
        "--cluster-name",
        "test-dev",
        "--skip-helm",
        case="missing-cluster",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Craft runtime and Onyx were not installed" in result.stdout
    assert commands == [
        ["kind", "get", "clusters"],
        [
            "kind",
            "create",
            "cluster",
            "--name",
            "test-dev",
            "--image",
            "kindest/node:v1.33.1",
        ],
        ["kubectl", "--context", "kind-test-dev", "get", "nodes"],
    ]


def test_refresh_refuses_unsaved_sandbox_before_builds(tmp_path: Path) -> None:
    result, commands = _run_script(tmp_path, "refresh-images.sh", case="occupied")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "pod/sandbox-unsaved-work" in result.stderr
    assert "No sandbox pods were deleted" in result.stderr
    assert "Stop host Onyx API, Celery workers, and beat processes" in result.stderr
    assert 'VS Code "(k8s)" services' in result.stderr
    assert "Restart them only after refresh succeeds" in result.stderr
    assert not any(command[:2] == ["docker", "build"] for command in commands)
    assert not any("patch" in command or "delete" in command for command in commands)


def test_refresh_help_states_host_process_prerequisite(tmp_path: Path) -> None:
    result, commands = _run_script(tmp_path, "refresh-images.sh", "--help")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Stop host Onyx API, Celery workers, and beat processes" in result.stdout
    assert 'VS Code "(k8s)" services' in result.stdout
    assert "Restart them only after refresh succeeds" in result.stdout
    assert "In-cluster rollouts do not stop host processes" in result.stdout
    assert commands == []


def test_missing_dev_environment_stops_before_image_changes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    dev_dir = repo / "deployment/helm/dev"
    dev_dir.mkdir(parents=True)
    (dev_dir.parent / "charts/onyx").mkdir(parents=True)
    for script in ("refresh-images.sh", "k8s-up.sh"):
        shutil.copy2(_DEV_DIR / script, dev_dir / script)
    pin_helper = Path("deployment/firecracker/install-pinned-firecracker.sh")
    (repo / pin_helper.parent).mkdir(parents=True)
    shutil.copy2(_REPO_ROOT / pin_helper, repo / pin_helper)
    result, commands = _run_script(
        tmp_path, "refresh-images.sh", "--prepare", case="fresh", dev_dir=dev_dir
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Image refresh requires uv and a synced development .venv" in result.stderr
    assert any(command[:2] == ["kind", "get"] for command in commands)
    assert not any(command[:2] == ["docker", "build"] for command in commands)
    assert not any(command[:2] == ["kind", "load"] for command in commands)
    assert not any("ctr" in command and "import" in command for command in commands)
    assert not any("patch" in command or "apply" in command for command in commands)


def test_failed_template_render_stops_before_image_changes(tmp_path: Path) -> None:
    result, commands = _run_script(tmp_path, "refresh-images.sh", case="failed-render")
    assert result.returncode == 1, result.stdout + result.stderr
    assert any(command[:2] == ["helm", "template"] for command in commands)
    assert not any(command[:2] == ["docker", "build"] for command in commands)
    assert not any(command[:2] == ["kind", "load"] for command in commands)
    assert not any("patch" in command or "apply" in command for command in commands)


@pytest.mark.parametrize("resource", ["namespace", "podtemplate"])
def test_prepare_does_not_treat_failed_reads_as_missing_resources(
    tmp_path: Path, resource: str
) -> None:
    result, commands = _run_script(
        tmp_path, "refresh-images.sh", "--prepare", case=f"{resource}-api-error"
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "API read failed" in result.stderr
    assert not any(command[:2] == ["docker", "build"] for command in commands)
    assert not any(command[:2] == ["kind", "load"] for command in commands)
    assert not any("patch" in command or "apply" in command for command in commands)


def test_setup_does_not_treat_failed_reads_as_a_fresh_install(tmp_path: Path) -> None:
    result, commands = _run_script(
        tmp_path,
        "k8s-up.sh",
        "--cluster-name",
        "test-dev",
        case="deployments-api-error",
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "API read failed" in result.stderr
    assert not any(command[:2] == ["kind", "load"] for command in commands)
    assert not any(command[:2] == ["helm", "upgrade"] for command in commands)
    assert not any("patch" in command or "apply" in command for command in commands)


def test_failed_setup_dependencies_preserve_live_image_tags(tmp_path: Path) -> None:
    result, commands = _run_script(
        tmp_path,
        "craft-up.sh",
        "--cluster-name",
        "test-dev",
        case="failed-dependencies",
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Helm dependency update failed" in result.stderr
    assert any(command[:2] == ["docker", "build"] for command in commands)
    assert any(command[:3] == ["helm", "dependency", "update"] for command in commands)
    assert not any(command[:2] == ["kind", "load"] for command in commands)
    assert not any("patch" in command or "apply" in command for command in commands)


@pytest.mark.parametrize("case", ["ready", "fresh"])
def test_prepare_does_not_replace_live_image_tags(tmp_path: Path, case: str) -> None:
    result, commands = _run_script(
        tmp_path, "refresh-images.sh", "--prepare", "--skip-build", case=case
    )
    assert result.returncode == 0, result.stdout + result.stderr
    loads = [
        command[3]
        for command in commands
        if command[:3] == ["kind", "load", "docker-image"]
    ]
    assert loads == (["onyxdotapp/onyx-backend:dev"] if case == "fresh" else [])
    imports = [
        command for command in commands if "ctr" in command and "import" in command
    ]
    assert len(imports) == (1 if case == "fresh" else 0)
    assert not any("patch" in command or "apply" in command for command in commands)


@pytest.mark.parametrize("case", ["occupied-after-apply", "pods-api-error-after-apply"])
def test_refresh_rechecks_sandboxes_after_applying_template(
    tmp_path: Path, case: str
) -> None:
    result, commands = _run_script(
        tmp_path, "refresh-images.sh", "--skip-build", case=case
    )
    assert result.returncode == 1, result.stdout + result.stderr
    expected_error = (
        "pod/sandbox-unsaved-work"
        if case == "occupied-after-apply"
        else "API read failed"
    )
    assert expected_error in result.stderr
    assert "Backend rollouts completed" not in result.stdout
    applied_templates = [
        index
        for index, command in enumerate(commands)
        if command[0] == "applied-template"
    ]
    assert len(applied_templates) == 1
    assert commands[applied_templates[0] + 1 :] == [
        [
            "kubectl",
            "--context",
            "kind-test-dev",
            "get",
            "namespace",
            "onyx-sandboxes",
            "--ignore-not-found",
            "-o",
            "name",
        ],
        [
            "kubectl",
            "--context",
            "kind-test-dev",
            "--namespace",
            "onyx-sandboxes",
            "get",
            "pods",
            "-o",
            "name",
        ],
    ]
    assert not any("delete" in command for command in commands)


def test_refresh_imports_retained_guest_through_devmapper_on_each_node(
    tmp_path: Path,
) -> None:
    result, commands = _run_script(
        tmp_path, "refresh-images.sh", "--skip-build", case="multi-node"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    imports = [
        command
        for command in commands
        if command[0] == "docker" and "ctr" in command and "import" in command
    ]
    assert imports == [
        [
            "docker",
            "exec",
            "-i",
            node,
            "ctr",
            "--namespace",
            "k8s.io",
            "images",
            "import",
            "--local",
            "--snapshotter",
            "devmapper",
            "--label",
            "io.cri-containerd.pinned=pinned",
            "-",
        ]
        for node in ("test-dev-control-plane", "test-dev-worker")
    ]
    old_pods_wait = next(
        index
        for index, command in enumerate(commands)
        if "wait" in command and "--for=delete" in command
    )
    template_apply = next(
        index for index, command in enumerate(commands) if "apply" in command
    )
    assert all(
        old_pods_wait < commands.index(command) < template_apply for command in imports
    )
    assert not any(
        command[:4] == ["kind", "load", "docker-image", "onyxdotapp/sandbox:dev"]
        for command in commands
    )
    assert [
        command for command in commands if command[0] == "imported-guest-config"
    ] == [
        ["imported-guest-config", "blobs/sha256/" + "a" * 64],
        ["imported-guest-config", "blobs/sha256/" + "a" * 64],
    ]
    inspections = [command for command in commands if "inspecti" in command]
    assert inspections == [
        [
            "docker",
            "exec",
            node,
            "crictl",
            "--runtime-endpoint",
            "unix:///run/containerd/containerd.sock",
            "--image-endpoint",
            "unix:///run/containerd/containerd.sock",
            "inspecti",
            "-o",
            "go-template",
            "--template",
            "{{.status.id}} {{.status.pinned}}",
            "docker.io/onyxdotapp/sandbox:dev",
        ]
        for node in ("test-dev-control-plane", "test-dev-worker")
    ]
    for node in ("test-dev-control-plane", "test-dev-worker"):
        node_validation = [
            "docker",
            "inspect",
            "-f",
            '{{ index .Config.Labels "io.x-k8s.kind.cluster" }}',
            node,
        ]
        assert node_validation in commands
        assert commands.index(node_validation) < commands.index(imports[0])


def test_failed_guest_import_stops_before_template_apply(tmp_path: Path) -> None:
    result, commands = _run_script(
        tmp_path, "refresh-images.sh", "--skip-build", case="failed-guest-import"
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "guest image import failed" in result.stderr
    assert any("ctr" in command and "import" in command for command in commands)
    assert not any("apply" in command for command in commands)
    assert "Backend rollouts completed" not in result.stdout


def test_guest_loader_accepts_classic_docker_config_digest(tmp_path: Path) -> None:
    result, commands = _run_script(
        tmp_path, "refresh-images.sh", "--skip-build", case="classic-guest-config"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert [
        command for command in commands if command[0] == "imported-guest-config"
    ] == [["imported-guest-config", "a" * 64 + ".json"]]
    assert any("inspecti" in command for command in commands)
    assert "Backend rollouts completed" in result.stdout


@pytest.mark.parametrize(
    ("case", "error"),
    [
        ("wrong-node-cluster", "expected kind cluster test-dev"),
        (
            "unsupported-guest-platform",
            "unsupported guest image platform: linux/ppc64le",
        ),
        ("ambiguous-guest-manifest", "expected exactly one saved guest image manifest"),
        ("invalid-guest-config", "invalid saved guest config digest"),
        ("failed-guest-save", "guest image save failed"),
        ("failed-guest-inspection", "guest image inspection failed"),
        ("wrong-guest-image", "guest image identity or retention mismatch"),
        ("unpinned-guest-image", "guest image identity or retention mismatch"),
    ],
)
def test_guest_loader_fails_closed_before_template_apply(
    tmp_path: Path, case: str, error: str
) -> None:
    result, commands = _run_script(
        tmp_path, "refresh-images.sh", "--skip-build", case=case
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert error in result.stderr
    assert not any("apply" in command for command in commands)
    assert "Backend rollouts completed" not in result.stdout
    if case in {
        "wrong-node-cluster",
        "unsupported-guest-platform",
        "ambiguous-guest-manifest",
        "invalid-guest-config",
        "failed-guest-save",
    }:
        assert not any("ctr" in command and "import" in command for command in commands)


@pytest.mark.parametrize("case", ["ready", "fresh"])
def test_setup_uses_shared_refresh_before_helm_upgrade(
    tmp_path: Path, case: str
) -> None:
    result, commands = _run_script(
        tmp_path, "k8s-up.sh", "--cluster-name", "test-dev", case=case
    )
    assert result.returncode == 0, result.stdout + result.stderr
    upgrades = [command for command in commands if command[:2] == ["helm", "upgrade"]]
    assert len(upgrades) == 1
    assert upgrades[0][upgrades[0].index("--kube-context") + 1] == "kind-test-dev"
    guest_loads = [
        command for command in commands if "ctr" in command and "import" in command
    ]
    assert len(guest_loads) == 1
    assert commands.index(guest_loads[0]) < commands.index(upgrades[0])
    assert any(
        "rollout" in command and "restart" in command for command in commands
    ) == (case == "ready")
    assert not any(
        command[:3] == ["kubectl", "config", "use-context"] for command in commands
    )


@pytest.mark.parametrize(
    "case", ["ready", "failed-rollout", "old-pod-remains", "occupied-after-rollout"]
)
def test_refresh_rolls_all_backends_before_loading_or_applying_guest(
    tmp_path: Path, case: str
) -> None:
    result, commands = _run_script(
        tmp_path, "refresh-images.sh", "--skip-build", case=case
    )
    patches = [command for command in commands if "patch" in command]
    assert [command[command.index("deployment") + 1] for command in patches] == [
        "onyx-api-server",
        "onyx-celery-worker-heavy",
        "onyx-celery-worker-scheduled-tasks",
        "onyx-sandbox-proxy",
        "onyx-sandbox-proxy",
    ]
    specs = [json.loads(command[-1])["spec"]["template"]["spec"] for command in patches]
    assert specs[0] == {
        "containers": [
            {
                "name": "api-server",
                "image": "onyxdotapp/onyx-backend:dev",
                "imagePullPolicy": "IfNotPresent",
            }
        ]
    }
    assert specs[-1] == {
        "initContainers": [
            {
                "name": "build-upstream-ca-bundle",
                "image": "onyxdotapp/onyx-backend:dev",
                "imagePullPolicy": "IfNotPresent",
            }
        ]
    }
    guest_loads = [
        index
        for index, command in enumerate(commands)
        if "ctr" in command and "import" in command
    ]
    applies = [index for index, command in enumerate(commands) if "apply" in command]
    if case != "ready":
        assert result.returncode == 1, result.stdout + result.stderr
        assert guest_loads == []
        assert applies == []
        return
    assert result.returncode == 0, result.stdout + result.stderr
    waits = [command for command in commands if "wait" in command]
    assert waits == [
        [
            "kubectl",
            "--context",
            "kind-test-dev",
            "--namespace",
            "onyx",
            "wait",
            "--for=delete",
            "pod/old-api",
            "pod/old-worker",
            "--timeout=300s",
        ]
    ]
    assert len(guest_loads) == 1
    assert len(applies) == 1
    assert commands.index(waits[0]) < guest_loads[0] < applies[0]
    assert [command for command in commands if command[0] == "applied-template"] == [
        ["applied-template", "kind: PodTemplate\nmetadata:\n  name: sandbox-pod\n"]
    ]
    rollouts = [command[-2] for command in commands if "status" in command]
    assert rollouts == [
        "deployment/onyx-api-server",
        "deployment/onyx-celery-worker-heavy",
        "deployment/onyx-celery-worker-scheduled-tasks",
        "deployment/onyx-sandbox-proxy",
    ]


def test_local_overlay_renders_matching_local_images() -> None:
    helm = shutil.which("helm")
    if helm is None:
        skip_or_fail("helm binary not available")
    result = subprocess.run(
        [
            helm,
            "template",
            "onyx",
            str(_REPO_ROOT / "deployment/helm/charts/onyx"),
            "--namespace",
            "onyx",
            "--kube-version",
            "1.33.1",
            "--values",
            str(_DEV_DIR / "values-localdev.yaml"),
            "--set",
            "auth.opensearch.existingSecret=onyx-opensearch",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    resources = [resource for resource in yaml.safe_load_all(result.stdout) if resource]
    template = next(
        resource for resource in resources if resource["kind"] == "PodTemplate"
    )
    assert (
        template["template"]["metadata"]["labels"]["onyx.app/sandbox-protocol"] == "2"
    )
    spec = template["template"]["spec"]
    assert spec["runtimeClassName"] == "kata-fc"
    for container in [*spec["containers"], *spec["initContainers"]]:
        assert container["image"] == "onyxdotapp/sandbox:dev"
        assert container["imagePullPolicy"] == "IfNotPresent"
    backends = [
        container
        for resource in resources
        if resource["kind"] == "Deployment"
        for container in resource["spec"]["template"]["spec"]["containers"]
        if container["image"].startswith("onyxdotapp/onyx-backend:")
    ]
    assert {container["name"] for container in backends} == {
        "api-server",
        "sandbox-proxy",
    }
    for container in backends:
        assert container["image"] == "onyxdotapp/onyx-backend:dev"
        assert container["imagePullPolicy"] == "IfNotPresent"


def test_compose_hook_uses_checkout_root_inside_git_commit() -> None:
    uv = shutil.which("uv")
    if uv is None or shutil.which("go") is None:
        skip_or_fail("uv and go binaries are required for the Compose hook")
    config = yaml.safe_load((_REPO_ROOT / ".pre-commit-config.yaml").read_text())
    hook = next(
        hook
        for repo in config["repos"]
        for hook in repo["hooks"]
        if hook.get("alias") == "docker-compose-sync"
    )
    args: list[str] = list(hook["args"])
    if args[-1] == "--write":
        args.pop()
    else:
        assert args[-1].endswith(" --write")
        args[-1] = args[-1].removesuffix(" --write")
    git_dir = subprocess.run(
        ["git", "rev-parse", "--absolute-git-dir"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    result = subprocess.run(
        [uv, "run", *args],
        cwd=_REPO_ROOT,
        env={**os.environ, "GIT_DIR": git_dir, "GIT_WORK_TREE": "."},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
