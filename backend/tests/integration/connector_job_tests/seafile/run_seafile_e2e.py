#!/usr/bin/env python3
"""Run the Seafile integration E2E suite with the required local services."""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
BACKEND_DIR = REPO_ROOT / "backend"
COMPOSE_DIR = REPO_ROOT / "deployment" / "docker_compose"
SEAFILE_E2E_TEST = "tests/integration/connector_job_tests/seafile/test_seafile_e2e.py"
COMPOSE_PROJECT_NAME = "onyx"
COMPOSE_FILES = ("docker-compose.yml", "docker-compose.dev.yml")
COMPOSE_PROFILES = ("s3-filestore",)
REQUIRED_SERVICES = (
    "relational_db",
    "cache",
    "opensearch",
    "minio",
    "inference_model_server",
)
DEFAULT_ENV = {
    "INTEGRATION_TESTS_MODE": "true",
    "USER_AUTH_SECRET": "test-secret",
    "POSTGRES_DB": "postgres",
    "FILE_STORE_BACKEND": "s3",
    "S3_ENDPOINT_URL": "http://localhost:9004",
    "S3_AWS_ACCESS_KEY_ID": "minioadmin",
    "S3_AWS_SECRET_ACCESS_KEY": "minioadmin",
}


def _run(
    cmd: list[str],
    *,
    cwd: Path = REPO_ROOT,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> None:
    print(f"+ {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, cwd=cwd, env=env, check=check)


def _compose_cmd(*args: str) -> list[str]:
    cmd = ["docker", "compose", "-p", COMPOSE_PROJECT_NAME]
    for compose_profile in COMPOSE_PROFILES:
        cmd.extend(("--profile", compose_profile))
    for compose_file in COMPOSE_FILES:
        cmd.extend(("-f", compose_file))
    cmd.extend(args)
    return cmd


def _docker_names(*args: str) -> list[str]:
    result = subprocess.run(
        ["docker", *args],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _compose_leftovers() -> list[str]:
    containers = _docker_names(
        "ps",
        "-a",
        "--filter",
        f"label=com.docker.compose.project={COMPOSE_PROJECT_NAME}",
        "--format",
        "{{.Names}}",
    )
    volumes = _docker_names(
        "volume",
        "ls",
        "--filter",
        f"label=com.docker.compose.project={COMPOSE_PROJECT_NAME}",
        "--format",
        "{{.Name}}",
    )
    networks = _docker_names(
        "network",
        "ls",
        "--filter",
        f"label=com.docker.compose.project={COMPOSE_PROJECT_NAME}",
        "--format",
        "{{.Name}}",
    )
    return [
        *(f"container:{name}" for name in containers),
        *(f"volume:{name}" for name in volumes),
        *(f"network:{name}" for name in networks),
    ]


def _cleanup_compose_stack(*, strict: bool) -> None:
    _run(
        _compose_cmd("down", "-v", "--remove-orphans"),
        cwd=COMPOSE_DIR,
        check=False,
    )
    leftovers = _compose_leftovers()
    if leftovers:
        message = "Compose cleanup left resources behind: " + ", ".join(leftovers)
        if strict:
            raise RuntimeError(message)
        print(f"WARNING: {message}", flush=True)


def _wait_for_tcp(name: str, host: str, port: int, timeout_s: int) -> None:
    deadline = time.monotonic() + timeout_s
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2):
                print(f"{name} is reachable at {host}:{port}", flush=True)
                return
        except OSError as exc:
            last_error = exc
            time.sleep(2)

    raise TimeoutError(
        f"Timed out waiting for {name} at {host}:{port}. Last error: {last_error}"
    )


def _wait_for_http(name: str, url: str, timeout_s: int) -> None:
    deadline = time.monotonic() + timeout_s
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status < 500:
                    print(f"{name} is reachable at {url}", flush=True)
                    return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            time.sleep(2)

    raise TimeoutError(
        f"Timed out waiting for {name} at {url}. Last error: {last_error}"
    )


def _wait_for_services(timeout_s: int) -> None:
    _wait_for_tcp("Postgres", "127.0.0.1", 5432, timeout_s)
    _wait_for_tcp("Redis", "127.0.0.1", 6379, timeout_s)
    _wait_for_tcp("OpenSearch", "127.0.0.1", 9200, timeout_s)
    _wait_for_tcp("MinIO", "127.0.0.1", 9004, timeout_s)
    _wait_for_http("model server", "http://127.0.0.1:9000/api/health", timeout_s)


def _pytest_env() -> dict[str, str]:
    env = os.environ.copy()
    for key, value in DEFAULT_ENV.items():
        env.setdefault(key, value)
    return env


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start local dependencies and run the Seafile integration E2E suite."
    )
    parser.add_argument(
        "--no-up",
        action="store_true",
        help="Do not start compose services; only check readiness and run pytest.",
    )
    parser.add_argument(
        "--keep-services",
        action="store_true",
        help="Do not shut down compose services or remove volumes after the run.",
    )
    parser.add_argument(
        "--cleanup-existing",
        action="store_true",
        help="With --no-up, also run docker compose down -v after pytest completes.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Seconds to wait for each required service.",
    )
    parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Extra pytest arguments. Prefix with --, e.g. -- -k multiple_libraries.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    should_cleanup = (
        not args.no_up or args.cleanup_existing
    ) and not args.keep_services

    try:
        if not args.no_up:
            _run(
                _compose_cmd("up", "-d", *REQUIRED_SERVICES),
                cwd=COMPOSE_DIR,
            )

        _wait_for_services(args.timeout)

        pytest_args = args.pytest_args
        if pytest_args and pytest_args[0] == "--":
            pytest_args = pytest_args[1:]

        _run(
            ["uv", "run", "pytest", "-q", SEAFILE_E2E_TEST, *pytest_args],
            cwd=BACKEND_DIR,
            env=_pytest_env(),
        )
    finally:
        if should_cleanup:
            _cleanup_compose_stack(strict=sys.exc_info()[0] is None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
