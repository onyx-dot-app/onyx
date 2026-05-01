"""Helpers for executing commands inside Docker sandbox containers.

Mirrors the ergonomics of the Kubernetes ``k8s_stream(... command=[...] ...)``
calls used throughout ``KubernetesSandboxManager`` so that the docker manager
reads naturally next to its k8s sibling: a single helper that runs a shell
script inside the container and returns combined stdout/stderr as a string.

Streaming variants are provided for snapshot tar pipelines where the response
can be many MB and we don't want it in memory all at once.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import docker  # type: ignore[import-untyped]
from docker.errors import APIError  # type: ignore[import-untyped]
from docker.errors import NotFound  # type: ignore[import-untyped]
from docker.models.containers import Container  # type: ignore[import-untyped]

from onyx.utils.logger import setup_logger

logger = setup_logger()


class DockerExecError(RuntimeError):
    """Raised when an exec inside a sandbox container exits non-zero."""

    def __init__(self, exit_code: int, output: str) -> None:
        super().__init__(
            f"docker exec failed with exit code {exit_code}: {output[:1000]}"
        )
        self.exit_code = exit_code
        self.output = output


def exec_shell(
    container: Container,
    script: str,
    *,
    user: str | None = None,
    workdir: str | None = None,
    env: dict[str, str] | None = None,
    timeout: float | None = None,  # noqa: ARG001 - reserved for future use
) -> str:
    """Run a shell script inside the container and return combined output.

    Equivalent shape to ``k8s_stream(... command=["/bin/sh", "-c", script])``.
    Raises ``DockerExecError`` on non-zero exit so callers can surface failures
    like the K8s code surfaces ``ApiException``.
    """
    try:
        exit_code, output = container.exec_run(
            cmd=["/bin/sh", "-c", script],
            user=user or "",
            workdir=workdir,
            environment=env,
            stdout=True,
            stderr=True,
            tty=False,
            demux=False,
        )
    except (APIError, NotFound) as e:
        raise RuntimeError(
            f"docker exec failed for container {container.name}: {e}"
        ) from e

    text = (
        output.decode("utf-8", errors="replace")
        if isinstance(output, bytes)
        else str(output)
    )
    if exit_code != 0:
        raise DockerExecError(exit_code, text)
    return text


def exec_stream_stdout(
    client: docker.DockerClient,
    container: Container,
    cmd: list[str],
    *,
    workdir: str | None = None,
) -> Iterator[bytes]:
    """Run a command and yield stdout chunks as raw bytes.

    Used for streaming a ``tar -czf -`` snapshot back through the docker socket
    without buffering the whole archive in memory. We deliberately drop stderr
    here — the underlying ``client.api.exec_create`` does not split streams when
    ``tty=False`` and ``demux=False``, but for tar producers that is fine
    because tar writes to stdout only and reports failures via exit code.
    """
    create = client.api.exec_create(
        container.id,
        cmd=cmd,
        stdout=True,
        stderr=True,
        tty=False,
        workdir=workdir,
    )
    exec_id = create["Id"]

    sock_or_stream: Any = client.api.exec_start(
        exec_id,
        detach=False,
        tty=False,
        stream=True,
        demux=False,
    )

    try:
        for chunk in sock_or_stream:
            if chunk:
                yield chunk
    finally:
        # Always inspect for exit code so callers can detect tar failures.
        result = client.api.exec_inspect(exec_id)
        exit_code = result.get("ExitCode")
        if exit_code not in (0, None):
            raise DockerExecError(int(exit_code), f"exec {cmd} exited {exit_code}")


def exec_write_stdin(
    client: docker.DockerClient,
    container: Container,
    cmd: list[str],
    payload: bytes,
    *,
    workdir: str | None = None,
) -> str:
    """Run a command, write ``payload`` to its stdin, return combined output.

    The Docker SDK does not expose a clean "send stdin then close" via the
    high-level ``exec_run``. We use the lower-level ``exec_create`` /
    ``exec_start(socket=True)`` to get a duplex socket, write the payload,
    half-close stdin, and drain stdout/stderr.
    """
    create = client.api.exec_create(
        container.id,
        cmd=cmd,
        stdin=True,
        stdout=True,
        stderr=True,
        tty=False,
        workdir=workdir,
    )
    exec_id = create["Id"]

    sock = client.api.exec_start(
        exec_id,
        detach=False,
        tty=False,
        stream=False,
        socket=True,
        demux=False,
    )

    # The SDK wraps the raw socket; the underlying socket is at ._sock.
    raw = sock._sock if hasattr(sock, "_sock") else sock

    try:
        view = memoryview(payload)
        offset = 0
        while offset < len(view):
            sent = raw.send(view[offset:])
            if sent == 0:
                break
            offset += sent
        try:
            raw.shutdown(1)  # half-close write side so reader sees EOF
        except OSError:
            pass

        # Drain stdout. Output is multiplexed (8-byte header + payload) when
        # tty=False; we strip headers here.
        chunks: list[bytes] = []
        while True:
            try:
                buf = raw.recv(65536)
            except OSError:
                break
            if not buf:
                break
            chunks.append(buf)
        raw_output = b"".join(chunks)
    finally:
        try:
            raw.close()
        except Exception:
            pass

    text = _strip_demux_headers(raw_output).decode("utf-8", errors="replace")

    result = client.api.exec_inspect(exec_id)
    exit_code = result.get("ExitCode")
    if exit_code not in (0, None):
        raise DockerExecError(int(exit_code), text)
    return text


def _strip_demux_headers(data: bytes) -> bytes:
    """Strip the 8-byte stream-multiplexing headers Docker prepends per chunk.

    Format: ``[stream_type(1)][padding(3)][size(4 BE)][payload(size)]``.
    Used when the exec was started without a TTY and stdout/stderr are
    interleaved on the same socket.
    """
    out = bytearray()
    i = 0
    n = len(data)
    while i + 8 <= n:
        header = data[i : i + 8]
        size = int.from_bytes(header[4:8], "big")
        i += 8
        end = min(i + size, n)
        out.extend(data[i:end])
        i = end
    if i < n:
        # Trailing partial frame (shouldn't normally happen) — append raw
        out.extend(data[i:])
    return bytes(out)
