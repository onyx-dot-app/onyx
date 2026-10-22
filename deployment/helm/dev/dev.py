#!/usr/bin/env python3
"""Local kind development commands shared by Make and VS Code."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NotRequired, TypedDict, cast

from runtime import Cluster

ROOT = Path(__file__).resolve().parents[3]
LABEL = "app.onyx.dev.image"
SOURCE_LABEL = "app.onyx.dev.source"
OWNER_LABEL = "app.onyx.dev.checkout"
IMAGES = {
    "backend": (
        os.environ.get("BACKEND_IMAGE", "onyxdotapp/onyx-backend:dev"),
        "backend",
    ),
    "sandbox": (
        os.environ.get("SANDBOX_IMAGE", "onyxdotapp/sandbox:dev"),
        "backend/onyx/server/features/build/sandbox/image",
    ),
}


class ImageConfig(TypedDict):
    Labels: NotRequired[dict[str, str] | None]


class ImageInfo(TypedDict):
    Config: ImageConfig


def run(
    *args: str,
    capture: bool = False,
    cwd: Path = ROOT,
    timeout: float | None = 120,
) -> str:
    """Bound short commands; callers can allow longer builds, loads, and cleanup."""
    result = subprocess.run(
        args,
        cwd=cwd,
        check=True,
        text=True,
        timeout=timeout,
        stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout.strip() if capture else ""


def source_hash(context: str) -> str:
    """Fingerprint tracked and unignored source contents, paths, and file modes."""
    paths = subprocess.check_output(
        [
            "git",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            context,
        ],
        cwd=ROOT,
        timeout=120,
    ).split(b"\0")
    digest = hashlib.sha256()
    for name in sorted(set(paths) - {b""}):
        path = ROOT / os.fsdecode(name)
        if path.is_symlink():
            contents = os.fsencode(os.readlink(path))
        elif path.is_file():
            contents = path.read_bytes()
        else:
            continue
        digest.update(name + b"\0" + str(path.lstat().st_mode).encode() + b"\0")
        digest.update(hashlib.sha256(contents).digest())
    return digest.hexdigest()


def nodes(cluster: str) -> list[str]:
    """Find the selected kind cluster nodes or reject a missing cluster."""
    result = run("kind", "get", "nodes", "--name", cluster, capture=True).splitlines()
    if not result:
        raise ValueError(f"kind cluster {cluster!r} does not exist")
    return result


def kube(
    args: argparse.Namespace,
    *command: str,
    capture: bool = False,
    timeout: float = 120,
) -> str:
    """Run kubectl against the selected local cluster and namespace."""
    return run(
        "kubectl",
        "--context",
        f"kind-{args.cluster_name}",
        "--request-timeout=30s",
        "-n",
        args.namespace,
        *command,
        capture=capture,
        timeout=timeout,
    )


def inspect_image(image: str) -> ImageInfo | None:
    """Inspect a Docker image without treating daemon failures as missing images."""
    run("docker", "info", "--format", "{{.ServerVersion}}", capture=True)
    result = subprocess.run(
        ["docker", "image", "inspect", image],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode:
        if "No such image" in result.stderr or "No such object" in result.stderr:
            return None
        raise ValueError(result.stderr.strip())
    return cast(ImageInfo, json.loads(result.stdout)[0])


def labels(info: ImageInfo) -> dict[str, str]:
    """Read image labels, including images with no labels."""
    return info["Config"].get("Labels") or {}


def images(args: argparse.Namespace) -> int:
    """Check, build, load, and apply selected images while preserving live sandboxes."""
    nodes(args.cluster_name)
    selected = [args.only] if args.only else list(IMAGES)
    stale = False
    for name in selected:
        image, context = IMAGES[name]
        fingerprint = source_hash(context)
        info = inspect_image(image)
        matches = info is not None and labels(info).get(SOURCE_LABEL) == fingerprint
        if args.check:
            print(
                f"{image}: {'matches checkout' if matches else 'missing or source changed'}"
            )
            stale |= not matches
            continue
        if args.reuse and info is None:
            raise ValueError(f"{image} is missing; omit --reuse to build it")
        if args.force or (info is None or (not args.reuse and not matches)):
            build_options: list[str] = []
            if ca_bundle := os.environ.get("CRAFT_BUILD_CA_BUNDLE"):
                bundle_path = Path(ca_bundle).expanduser().resolve(strict=True)
                build_options = ["--secret", f"id=build_ca_bundle,src={bundle_path}"]
            run(
                "docker",
                "build",
                *build_options,
                "--label",
                f"{LABEL}=true",
                "--label",
                f"{SOURCE_LABEL}={fingerprint}",
                "--label",
                f"{OWNER_LABEL}={ROOT}",
                "-t",
                image,
                str(ROOT / context),
                timeout=None,
            )
        else:
            print(f"Reusing {image}; no build needed")
        run(
            "kind",
            "load",
            "docker-image",
            image,
            "--name",
            args.cluster_name,
            timeout=None,
        )
        if args.load_only:
            continue
        if name == "backend":
            # Update the actual workload image, not just its rollout timestamp.
            for deployment in ("onyx-sandbox-proxy", "onyx-api-server"):
                workload = json.loads(
                    kube(
                        args,
                        "get",
                        "deployment",
                        deployment,
                        "-o",
                        "json",
                        capture=True,
                    )
                )
                containers = workload["spec"]["template"]["spec"]["containers"]
                patches = []
                for index, container in enumerate(containers):
                    # Telepresence's traffic-agent must retain its own image.
                    if container["name"] not in {"api-server", "sandbox-proxy"}:
                        continue
                    patches.extend(
                        [
                            {
                                "op": "add",
                                "path": f"/spec/template/spec/containers/{index}/image",
                                "value": image,
                            },
                            {
                                "op": "add",
                                "path": f"/spec/template/spec/containers/{index}/imagePullPolicy",
                                "value": "IfNotPresent",
                            },
                        ]
                    )
                kube(
                    args,
                    "patch",
                    "deployment",
                    deployment,
                    "--type=json",
                    "-p",
                    json.dumps(patches),
                )
                kube(args, "rollout", "restart", f"deployment/{deployment}")
                kube(
                    args,
                    "rollout",
                    "status",
                    f"deployment/{deployment}",
                    "--timeout=180s",
                    "--request-timeout=200s",
                    timeout=210,
                )
        else:
            template = json.loads(
                run(
                    "kubectl",
                    "--context",
                    f"kind-{args.cluster_name}",
                    "--request-timeout=30s",
                    "-n",
                    args.sandbox_namespace,
                    "get",
                    "podtemplate",
                    "sandbox-pod",
                    "-o",
                    "json",
                    capture=True,
                )
            )
            spec = template["template"]["spec"]
            patches = []
            for group in ("containers", "initContainers"):
                for index, container in enumerate(spec.get(group, [])):
                    if container["name"] not in {"sandbox", "sandbox-init", "sidecar"}:
                        continue
                    for field, value in (
                        ("image", image),
                        ("imagePullPolicy", "IfNotPresent"),
                    ):
                        patches.append(
                            {
                                "op": "add",
                                "path": f"/template/spec/{group}/{index}/{field}",
                                "value": value,
                            }
                        )
            if not patches:
                raise ValueError("Sandbox PodTemplate has no recognized containers")
            run(
                "kubectl",
                "--context",
                f"kind-{args.cluster_name}",
                "--request-timeout=30s",
                "-n",
                args.sandbox_namespace,
                "patch",
                "podtemplate",
                "sandbox-pod",
                "--type=json",
                "-p",
                json.dumps(patches),
            )
            print("Existing sandboxes retain their image. No live sandbox was deleted.")
        kube(
            args,
            "get",
            "pods",
            "-o",
            "custom-columns=NAME:.metadata.name,IMAGE:.spec.containers[*].image,IMAGE_ID:.status.containerStatuses[*].imageID",
        )
    return int(stale)


def disk(args: argparse.Namespace) -> None:
    """Report host Docker storage and each selected kind node image store."""
    run("docker", "system", "df")
    for node in nodes(args.cluster_name):
        print(f"\nkind node: {node}", flush=True)
        run("docker", "exec", node, "df", "-h", "/var/lib/containerd")
        run("docker", "exec", node, "crictl", "images")


def doctor(args: argparse.Namespace) -> int:
    """Inspect prerequisites without changing the cluster or exposing secrets."""
    failures = 0

    def report(level: str, message: str) -> None:
        """Print one diagnostic result and count required failures."""
        nonlocal failures
        failures += level == "FAIL"
        print(f"{level}: {message}", flush=True)

    def probe(*command: str) -> subprocess.CompletedProcess[str] | None:
        """Capture diagnostic commands without exposing their output on failure."""
        try:
            return subprocess.run(
                command,
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None

    available = {
        name: shutil.which(name)
        for name in ("docker", "kind", "kubectl", "helm", "telepresence", "uv")
    }
    for name, path in available.items():
        report("PASS" if path else "FAIL", f"{name}: {path or 'missing from PATH'}")

    free_gib = shutil.disk_usage(ROOT).free / 1024**3
    report(
        "PASS" if free_gib >= 10 else "WARN",
        f"Checkout filesystem: {free_gib:.1f} GiB free; Docker storage can use another filesystem",
    )
    if available["docker"]:
        result = probe("docker", "info", "--format", "{{.ServerVersion}}")
        report(
            "PASS" if result is not None and result.returncode == 0 else "FAIL",
            "Docker daemon access"
            + (
                f": {result.stdout.strip()}"
                if result is not None and result.returncode == 0
                else "; check the daemon and socket permissions"
            ),
        )

    context = f"kind-{args.cluster_name}"
    if available["kubectl"]:
        result = probe(
            "kubectl",
            "--context",
            context,
            "--request-timeout=10s",
            "version",
            "-o",
            "json",
        )
        if result is not None and result.returncode == 0:
            versions = json.loads(result.stdout)
            client = versions["clientVersion"]["gitVersion"]
            server = versions["serverVersion"]["gitVersion"]
            client_match = re.match(r"v(\d+)\.(\d+)", client)
            server_match = re.match(r"v(\d+)\.(\d+)", server)
            supported = (
                client_match is not None
                and server_match is not None
                and client_match[1] == server_match[1]
                and abs(int(client_match[2]) - int(server_match[2])) <= 1
            )
            report(
                "PASS" if supported else "FAIL",
                f"kubectl {client}; server {server}; supported minor-version skew is at most one",
            )
            native_sidecars = server_match is not None and (
                int(server_match[1]),
                int(server_match[2]),
            ) >= (1, 33)
            report(
                "PASS" if native_sidecars else "FAIL",
                "Craft requires Kubernetes 1.33 or later",
            )
            result = probe(
                "kubectl",
                "--context",
                context,
                "--request-timeout=10s",
                "get",
                "nodes",
                "-o",
                "json",
            )
            items = (
                json.loads(result.stdout)["items"]
                if result is not None and result.returncode == 0
                else []
            )
            ready = bool(items) and all(
                any(
                    c["type"] == "Ready" and c["status"] == "True"
                    for c in node["status"].get("conditions", [])
                )
                for node in items
            )
            report("PASS" if ready else "FAIL", f"{context}: node readiness")
        else:
            report(
                "FAIL",
                f"{context}: API unavailable; start or resume the selected cluster",
            )

        result = probe(
            "kubectl",
            "--context",
            context,
            "--request-timeout=10s",
            "-n",
            args.sandbox_namespace,
            "get",
            "podtemplate",
            "sandbox-pod",
            "-o",
            "json",
        )
        if result is not None and result.returncode == 0:
            spec = json.loads(result.stdout)["template"]["spec"]
            containers = [
                c
                for group in ("containers", "initContainers")
                for c in spec.get(group, [])
                if c["name"] in {"sandbox", "sandbox-init", "sidecar"}
            ]
            matches = {c["name"] for c in containers} == {
                "sandbox",
                "sandbox-init",
                "sidecar",
            } and all(
                c["image"] == IMAGES["sandbox"][0]
                and c.get("imagePullPolicy") in {"IfNotPresent", "Never"}
                for c in containers
            )
            report(
                "PASS" if matches else "FAIL",
                "Sandbox PodTemplate uses the selected local image without registry pulls; repair with make craft-sandbox-image",
            )
        else:
            report("FAIL", "Sandbox PodTemplate unavailable; run make craft-up")

    if available["telepresence"]:
        result = probe("telepresence", "status", "--format", "json")
        status = (
            json.loads(result.stdout)
            if result is not None and result.returncode == 0
            else {}
        )
        user = status.get("user_daemon", {})
        connected = (
            user.get("kubernetes_context") == context
            and user.get("namespace") == args.namespace
            and user.get("status") == "Connected"
            and status.get("root_daemon", {}).get("running", False)
        )
        report(
            "PASS" if connected else "FAIL",
            f"Telepresence connection to {context}/{args.namespace}"
            + (
                ""
                if connected
                else "; run telepresence connect in an interactive terminal for sudo authorization"
            ),
        )
        version = user.get("version", "")
        report(
            "PASS" if version.removeprefix("v").startswith("2.") else "FAIL",
            f"Telepresence v2 daemon: {version or 'not running'}",
        )

    binary = ROOT / ".venv/bin/python"
    report(
        "PASS" if binary.is_file() else "FAIL", "Checkout Python environment (.venv)"
    )
    if available["uv"]:
        result = probe(
            "uv",
            "sync",
            "--check",
            "--offline",
            "--frozen",
            "--no-default-groups",
            "--group",
            "backend",
            "--group",
            "dev",
            "--group",
            "ee",
        )
        report(
            "PASS" if result is not None and result.returncode == 0 else "FAIL",
            "Checkout Python dependencies (backend, dev, ee)"
            + (
                ""
                if result is not None and result.returncode == 0
                else "; run uv sync --frozen --no-default-groups --group backend --group dev --group ee"
            ),
        )
    if binary.is_file():
        script = """import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from runtime import Cluster
cluster = Cluster(Path(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5])
env = cluster.environment()
required = ('POSTGRES_HOST', 'SANDBOX_PROXY_HOST', 'SANDBOX_CONTAINER_IMAGE', 'ONYX_SERVER_URL', 'ONYX_SANDBOX_PUSH_PRIVATE_KEY')
print(json.dumps({
    'missing': [key for key in required if not env.get(key) or env[key].startswith('<')],
    'model_key': bool(env.get('GEN_AI_API_KEY')),
    'image': env.get('SANDBOX_CONTAINER_IMAGE') == sys.argv[6],
}))
"""
        result = probe(
            str(binary),
            "-c",
            script,
            str(Path(__file__).parent),
            str(ROOT),
            args.cluster_name,
            args.namespace,
            args.sandbox_namespace,
            IMAGES["sandbox"][0],
        )
        if result is None or result.returncode:
            report(
                "FAIL",
                "Cannot resolve deployed API configuration; check cluster access, secrets, and Python dependencies",
            )
        else:
            env_status = json.loads(result.stdout)
            missing = env_status["missing"]
            report(
                "FAIL" if missing else "PASS",
                "Effective Craft configuration"
                + (f": fill {', '.join(missing)}" if missing else " is available"),
            )
            report(
                "PASS" if env_status["image"] else "FAIL",
                "Effective sandbox image matches the selected local image",
            )
            report(
                "PASS" if env_status["model_key"] else "WARN",
                "GEN_AI_API_KEY is set"
                if env_status["model_key"]
                else "GEN_AI_API_KEY is unset; agent turns need a configured model provider",
            )
    print(f"Doctor finished: {failures} failed check(s). No resources changed.")
    return int(failures > 0)


def clean(args: argparse.Namespace) -> None:
    """Preview or remove unused checkout images, with separate optional builder cache cleanup."""
    candidates = run(
        "docker",
        "image",
        "ls",
        "-q",
        "--filter",
        "dangling=true",
        "--filter",
        f"label={LABEL}=true",
        capture=True,
    ).splitlines()
    for image in sorted(set(candidates)):
        info = inspect_image(image)
        if info is None or labels(info).get(OWNER_LABEL) != str(ROOT):
            continue
        if run("docker", "ps", "-aq", "--filter", f"ancestor={image}", capture=True):
            continue
        print(
            f"{'Removing' if args.apply else 'Would remove'} unused checkout image {image}",
            flush=True,
        )
        if args.apply:
            run("docker", "image", "rm", image, timeout=None)
    if args.build_cache:
        print(
            "Build cache cleanup affects the selected Docker builder, across all projects.",
            flush=True,
        )
        print(
            "Keeps a 10GB cache target and only considers entries unused for seven days.",
            flush=True,
        )
        if args.apply:
            run(
                "docker",
                "builder",
                "prune",
                "--force",
                "--filter",
                "until=168h",
                "--keep-storage",
                "10GB",
                timeout=None,
            )
    print("Volumes, tagged images and kind runtime images are preserved.")


def cluster_runtime(args: argparse.Namespace) -> Cluster:
    """Bind shared runtime commands to the selected development environment."""
    return Cluster(ROOT, args.cluster_name, args.namespace, args.sandbox_namespace)


def readiness(args: argparse.Namespace) -> None:
    """Check the selected infrastructure or application readiness stage."""
    if args.stage == "infrastructure":
        cluster_runtime(args).infrastructure_ready(args.timeout)
    else:
        cluster_runtime(args).application_ready(args.frontend_url, args.timeout)


def pause_resume(args: argparse.Namespace) -> None:
    """Stop or restart cluster nodes while preserving their data."""
    cluster_nodes = nodes(args.cluster_name)
    if args.command == "pause":
        # Never quit a Telepresence connection to another cluster.
        status = json.loads(
            run("telepresence", "status", "--format", "json", capture=True)
        )
        connection = status.get("user_daemon", {})
        if connection.get("kubernetes_context") == f"kind-{args.cluster_name}":
            run("telepresence", "quit")
        run("docker", "stop", *cluster_nodes)
        print(
            "Cluster data preserved. Stop your local VS Code launch compound separately."
        )
    else:
        run("docker", "start", *cluster_nodes)
        kube(
            args,
            "wait",
            "--for=condition=Ready",
            "nodes",
            "--all",
            "--timeout=180s",
            "--request-timeout=200s",
            timeout=210,
        )
        cluster_runtime(args).infrastructure_ready()
        cluster_runtime(args).connect()
        print(
            "Cluster resumed. Relaunch your local services to restore the API intercept."
        )


def migrate(args: argparse.Namespace) -> None:
    """Inspect or upgrade the selected database after validating local migration prerequisites."""
    import psutil

    env = cluster_runtime(args).database_environment(args.env_file)
    host = env.get("POSTGRES_HOST", "localhost")
    port = env.get("POSTGRES_PORT", "5432")
    if args.operation == "upgrade":
        for proc in psutil.process_iter(["pid", "cmdline", "cwd", "uids"]):
            command = proc.info["cmdline"] or []
            directory = proc.info["cwd"]
            owner = proc.info["uids"]
            if (
                not directory
                or not Path(directory).is_relative_to(ROOT)
                or owner is None
                or owner.real != os.getuid()
            ):
                continue
            launcher = str(ROOT / "deployment/helm/dev/launch.py")
            shared_launch = any(
                str((base / arg).resolve()) == launcher
                for arg in command
                if Path(arg).name == "launch.py"
                for base in (Path(directory), ROOT)
            ) and any(role in command for role in ("api", "celery"))
            api = "onyx.main:app" in command
            worker = any("celery" in Path(arg).name for arg in command) and any(
                arg.startswith("onyx.background.") for arg in command
            )
            if shared_launch or api or worker:
                raise ValueError(
                    f"Stop local Onyx API/workers before migration (PID {proc.pid})"
                )
    run(
        "telepresence",
        "connect",
        "--context",
        f"kind-{args.cluster_name}",
        "-n",
        args.namespace,
    )
    print(f"Database: {host}:{port}; checkout: {ROOT}", flush=True)
    binary = ROOT / ".venv/bin/python"
    subprocess.run(
        [str(binary), "-m", "alembic", "current"],
        cwd=ROOT / "backend",
        env=env,
        check=True,
        timeout=120,
    )
    if args.operation == "upgrade":
        subprocess.run(
            [str(binary), "-m", "alembic", "upgrade", "head"],
            cwd=ROOT / "backend",
            env=env,
            check=True,
            timeout=None,
        )
        subprocess.run(
            [str(binary), "-m", "alembic", "current"],
            cwd=ROOT / "backend",
            env=env,
            check=True,
            timeout=120,
        )


def main() -> int:
    """Dispatch local development commands and return their exit status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cluster-name", default="onyx-dev")
    parser.add_argument("--namespace", default="onyx")
    parser.add_argument("--sandbox-namespace", default="onyx-sandboxes")
    commands = parser.add_subparsers(dest="command", required=True)
    image_parser = commands.add_parser("images")
    image_parser.add_argument("--only", choices=list(IMAGES))
    action = image_parser.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true")
    action.add_argument("--force", action="store_true")
    action.add_argument("--reuse", action="store_true")
    image_parser.add_argument("--load-only", action="store_true")
    commands.add_parser("disk")
    commands.add_parser("doctor")
    commands.add_parser("connect")
    commands.add_parser("intercept")
    ready = commands.add_parser("ready")
    ready.add_argument(
        "--stage", choices=("infrastructure", "application"), default="application"
    )
    ready.add_argument("--timeout", type=float, default=600)
    ready.add_argument(
        "--frontend-url",
        default=os.environ.get("CRAFT_FRONTEND_URL", "http://localhost:3000"),
    )
    cleanup = commands.add_parser("clean")
    cleanup.add_argument("--apply", action="store_true")
    cleanup.add_argument("--build-cache", action="store_true")
    commands.add_parser("pause")
    commands.add_parser("resume")
    migration = commands.add_parser("migrate")
    migration.add_argument("operation", choices=["status", "upgrade"])
    migration.add_argument("--env-file", type=Path, help="Defaults to .vscode/.env.k8s")
    args = parser.parse_args()
    try:
        if args.command == "images":
            return images(args)
        if args.command == "doctor":
            return doctor(args)
        if args.command == "connect":
            cluster_runtime(args).connect()
        elif args.command == "intercept":
            cluster_runtime(args).intercept()
        elif args.command == "ready":
            readiness(args)
        elif args.command == "disk":
            disk(args)
        elif args.command == "clean":
            clean(args)
        elif args.command == "migrate":
            migrate(args)
        else:
            pause_resume(args)
    except (
        ValueError,
        OSError,
        ImportError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
