"""Starts the mock server in a child process, for tests and scripts."""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

_APP_DIR = Path(__file__).resolve().parents[1]
_STARTUP_SECONDS = 60
_POLL_SECONDS = 0.2


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_mock_server(
    config: dict[str, Any] | None = None,
) -> tuple[subprocess.Popen[bytes], str]:
    """Starts the mock server on a free port and waits until it answers.
    The caller stops the process."""
    port = _free_port()
    env = dict(os.environ)
    if config:
        env["MOCK_SHAREPOINT_CONFIG"] = json.dumps(config)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "mock_sharepoint.app:app",
            "--app-dir",
            str(_APP_DIR),
            "--port",
            str(port),
            "--log-level",
            "warning",
            "--timeout-keep-alive",
            "120",
        ],
        env=env,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + _STARTUP_SECONDS
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{url}/health", timeout=1).status_code == 200:
                return process, url
        except httpx.HTTPError:
            pass
        # Waits for the next try, and sees a server that exits.
        try:
            process.wait(timeout=_POLL_SECONDS)
        except subprocess.TimeoutExpired:
            continue
        raise RuntimeError("The mock SharePoint server exited during startup")
    process.terminate()
    raise RuntimeError(
        f"The mock SharePoint server did not start within {_STARTUP_SECONDS} seconds"
    )
