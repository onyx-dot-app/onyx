#!/usr/bin/env python3
"""Launch a local Craft process with the deployed cluster configuration."""

import argparse
import os
import runpy
import subprocess
import sys
from pathlib import Path

from runtime import Cluster

ROOT = Path(__file__).resolve().parents[3]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cluster-name", default=os.environ.get("CLUSTER_NAME", "onyx-dev")
    )
    parser.add_argument("--namespace", default=os.environ.get("NAMESPACE", "onyx"))
    parser.add_argument("--sandbox-namespace", default="onyx-sandboxes")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("role", choices=("api", "celery", "ready"))
    parser.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    cluster = Cluster(ROOT, args.cluster_name, args.namespace, args.sandbox_namespace)
    if args.role == "ready":
        cluster.application_ready(
            os.environ.get("CRAFT_FRONTEND_URL", "http://localhost:3000")
        )
        return
    env = cluster.environment(args.env_file)
    # Preserve debugger-provided process settings over personal file defaults.
    for key in ("LOG_LEVEL", "PYTHONUNBUFFERED", "ENABLE_MULTIPASS_INDEXING"):
        if key in os.environ:
            env[key] = os.environ[key]
    os.environ.update(env)
    backend = ROOT / "backend"
    os.chdir(backend)
    sys.path.insert(0, str(backend))
    forwarded = args.args[1:] if args.args[:1] == ["--"] else args.args
    if args.role == "api":
        sys.argv = [
            "uvicorn",
            "onyx.main:app",
            "--reload",
            "--reload-exclude",
            str(backend / "onyx/skills/builtin"),
            "--reload-exclude",
            str(backend / "onyx/server/features/build/sandbox/image"),
            "--port",
            "8080",
            *forwarded,
        ]
        runpy.run_module("uvicorn", run_name="__main__")
    else:
        sys.argv = [str(backend / "scripts/dev_celery_reload.py"), *forwarded]
        runpy.run_path(sys.argv[0], run_name="__main__")


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
