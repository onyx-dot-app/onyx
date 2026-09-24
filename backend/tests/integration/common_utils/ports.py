import socket
import subprocess
import time

STARTUP_TIMEOUT_SECONDS = 30.0


def available_port(bind_host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((bind_host, 0))
        return int(sock.getsockname()[1])


def wait_for_port(
    host: str,
    port: int,
    process: subprocess.Popen[bytes] | None = None,
    timeout_s: float = STARTUP_TIMEOUT_SECONDS,
) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise RuntimeError(
                f"Process exited during startup with code {process.returncode}"
            )
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            try:
                sock.connect((host, port))
                return
            except OSError:
                time.sleep(0.1)
    raise TimeoutError(f"Timed out waiting for {host}:{port}")
