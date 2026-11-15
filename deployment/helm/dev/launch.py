#!/usr/bin/env python3
"""Launch a local Craft process with the deployed cluster configuration."""

import argparse
import contextlib
import os
import runpy
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import remote
from runtime import Cluster, application_ready

ROOT = Path(__file__).resolve().parents[3]


@contextlib.contextmanager
def remote_environment(args: argparse.Namespace) -> Iterator[dict[str, str]]:
    """Resolve the remote api env; refuse a mismatched cluster or migration head."""
    profile = remote.load_profile(ROOT, args.profile)
    cluster = remote.RemoteCluster.from_profile(
        ROOT, profile, args.context or os.environ.get(remote.CONTEXT_ENV)
    )
    remote.require_telepresence(cluster, cluster.verify_server())
    workload = cluster.api_workload()
    env = cluster.local_environment(
        args.env_file, profile_env=profile.local_env, frontend_url=frontend_url()
    )
    with remote.secret_files(cluster, env, workload) as resolved:
        remote.require_heads_match(ROOT, resolved)
        yield resolved


def frontend_url() -> str:
    return os.environ.get("CRAFT_FRONTEND_URL", remote.DEFAULT_FRONTEND_URL)


def requested_port(args: argparse.Namespace) -> int | None:
    if args.port is not None:
        return args.port
    value = os.environ.get("CRAFT_API_PORT")
    return int(value) if value else None


def run_web(args: argparse.Namespace) -> None:
    """Run the Next.js dev server against the local API."""
    from dotenv import dotenv_values

    env = dict(os.environ)
    path = ROOT / ".vscode/.env.web"
    if path.is_file():
        env.update({k: v for k, v in dotenv_values(path).items() if v is not None})
    port = requested_port(args) or remote.DEFAULT_API_PORT
    env["INTERNAL_URL"] = f"http://127.0.0.1:{port}"
    raise SystemExit(subprocess.call(["bun", "run", "dev"], cwd=ROOT / "web", env=env))


def main() -> None:
    """Resolve cluster configuration and launch the selected local application or readiness check."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        choices=("kind", remote.TARGET),
        default=os.environ.get("CRAFT_TARGET", "kind"),
    )
    parser.add_argument(
        "--profile", type=Path, help=f"{remote.TARGET} profile; or {remote.PROFILE_ENV}"
    )
    parser.add_argument(
        "--context", help=f"A context the {remote.TARGET} profile allows"
    )
    parser.add_argument("--port", type=int, help="Local API port; or CRAFT_API_PORT")
    parser.add_argument(
        "--cluster-name", default=os.environ.get("CLUSTER_NAME", "onyx-dev")
    )
    parser.add_argument("--namespace", default=os.environ.get("NAMESPACE", "onyx"))
    parser.add_argument("--sandbox-namespace", default="onyx-sandboxes")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("role", choices=("api", "celery", "ready", "web"))
    parser.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.role == "web":
        run_web(args)
        return
    if args.target == remote.TARGET:
        if args.role == "celery":
            raise ValueError(
                f"Local Celery workers are not allowed against {remote.TARGET}; "
                "they would take tasks from the shared queues"
            )
        if args.role == "ready":
            application_ready(frontend_url())
            return
        with remote_environment(args) as env:
            port = remote.pick_port(requested_port(args))
            if port != remote.DEFAULT_API_PORT:
                print(
                    f"Local API on port {port}. Start the web server with "
                    f"ods craft-dev web --port {port}",
                    flush=True,
                )
            run_api(env, args.args, host="127.0.0.1", port=port)
        return
    cluster = Cluster(ROOT, args.cluster_name, args.namespace, args.sandbox_namespace)
    if args.role == "ready":
        cluster.application_ready(frontend_url())
        return
    env = cluster.environment(args.env_file)
    if args.role == "api":
        run_api(env, args.args)
    else:
        prepare(env)
        sys.argv = [
            str(ROOT / "backend/scripts/dev_celery_reload.py"),
            *forwarded(args.args),
        ]
        runpy.run_path(sys.argv[0], run_name="__main__")


def forwarded(extra: list[str]) -> list[str]:
    return extra[1:] if extra[:1] == ["--"] else extra


def prepare(env: dict[str, str]) -> None:
    # Preserve debugger-provided process settings over personal file defaults.
    for key in ("LOG_LEVEL", "PYTHONUNBUFFERED", "ENABLE_MULTIPASS_INDEXING"):
        if key in os.environ:
            env[key] = os.environ[key]
    os.environ.update(env)
    backend = ROOT / "backend"
    os.chdir(backend)
    sys.path.insert(0, str(backend))


def run_api(
    env: dict[str, str], extra: list[str], host: str | None = None, port: int = 8080
) -> None:
    prepare(env)
    backend = ROOT / "backend"
    sys.argv = [
        "uvicorn",
        "onyx.main:app",
        "--reload",
        "--reload-exclude",
        str(backend / "onyx/skills/builtin"),
        "--reload-exclude",
        str(backend / "onyx/server/features/build/sandbox/image"),
        *(("--host", host) if host else ()),
        "--port",
        str(port),
        *forwarded(extra),
    ]
    runpy.run_module("uvicorn", run_name="__main__")


if __name__ == "__main__":
    try:
        main()
    except (
        ValueError,
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
