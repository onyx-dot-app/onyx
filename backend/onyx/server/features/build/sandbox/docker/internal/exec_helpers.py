"""Shared docker exec primitives for the Docker sandbox backend.

These helpers wrap ``docker.client.containers.Container.exec_run`` (and the
lower-level ``exec_create`` / ``exec_start`` API for streaming) into a small
collection of focused primitives:

- ``run_in_container``: capture stdout/stderr/exit code from a one-shot exec.
- ``stream_stdin_to_container``: pipe bytes into a remote process's stdin.
- ``stream_stdout_from_container``: stream a remote process's stdout back to
  the caller (used by snapshot creation).

The Docker SDK's ``exec_run`` is sufficient for the simple "run a script and
read its output" cases that make up most of the sandbox lifecycle. The
streaming helpers reach down to the low-level ``APIClient`` because the SDK's
high-level API does not expose the raw socket needed to pipe data through
stdin/stdout reliably.

All helpers raise :class:`ExecError` on a non-zero exit code or transport
failure. Callers translate to ``FatalWriteError`` /
``RetriableWriteError`` / ``RuntimeError`` as appropriate.
"""

from __future__ import annotations

import socket
import struct
from collections.abc import Generator
from dataclasses import dataclass

from docker.errors import APIError
from docker.errors import NotFound
from docker.models.containers import Container

from onyx.utils.logger import setup_logger

logger = setup_logger()


# Docker multiplexed stream frame header is 8 bytes:
#   byte 0: stream type (1=stdout, 2=stderr)
#   bytes 1-3: zero
#   bytes 4-7: big-endian uint32 frame length
_FRAME_HEADER_BYTES = 8
_FRAME_STDOUT = 1
_FRAME_STDERR = 2


@dataclass(frozen=True)
class ExecResult:
    """Result of a one-shot ``run_in_container`` invocation."""

    exit_code: int
    stdout: bytes
    stderr: bytes

    @property
    def stdout_text(self) -> str:
        return self.stdout.decode("utf-8", errors="replace")

    @property
    def stderr_text(self) -> str:
        return self.stderr.decode("utf-8", errors="replace")


class ExecError(RuntimeError):
    """Raised when a docker exec invocation fails.

    ``exit_code`` is ``None`` when the failure occurred before the process
    could be started (e.g. container missing, transport error).
    """

    def __init__(
        self,
        message: str,
        *,
        exit_code: int | None = None,
        stdout: bytes = b"",
        stderr: bytes = b"",
    ) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


def _command_summary(command: list[str] | str) -> str:
    """Render a command for inclusion in error messages without leaking secrets.

    Setup scripts contain inlined ``printf '%s' '<opencode.json>' > ...``
    invocations where ``<opencode.json>`` includes the LLM API key. Including
    the full script in an exception message would leak that key into
    api_server logs on any setup failure.

    Strategy: keep the argv head (``/bin/sh -c``) but replace any argument
    longer than 200 chars with a length-tagged placeholder.
    """
    if isinstance(command, str):
        return (
            f"<shell script: {len(command)} bytes>"
            if len(command) > 200
            else (repr(command))
        )
    summarized: list[str] = []
    for arg in command:
        if isinstance(arg, str) and len(arg) > 200:
            summarized.append(f"<shell script: {len(arg)} bytes>")
        else:
            summarized.append(arg)
    return repr(summarized)


def run_in_container(
    container: Container,
    command: list[str] | str,
    *,
    user: str | None = None,
    workdir: str | None = None,
    environment: dict[str, str] | None = None,
    check: bool = True,
) -> ExecResult:
    """Execute ``command`` inside ``container`` and capture output.

    Wraps ``Container.exec_run`` with ``demux=True`` so stdout and stderr are
    returned as separate byte strings.

    Args:
        container: A running ``docker.models.containers.Container``.
        command: A shell list (preferred) or a single shell string.
        user: Optional user override (``uid:gid`` or username).
        workdir: Working directory inside the container.
        environment: Extra environment variables for the exec.
        check: If True (default), raise :class:`ExecError` on a non-zero exit
            code.

    Returns:
        :class:`ExecResult` with exit code and captured streams.
    """
    try:
        exec_result = container.exec_run(
            cmd=command,
            user=user or "",
            workdir=workdir,
            environment=environment,
            demux=True,
            tty=False,
            stdin=False,
            stdout=True,
            stderr=True,
        )
    except (APIError, NotFound) as e:
        raise ExecError(f"exec_run failed: {e}") from e

    exit_code: int = exec_result.exit_code if exec_result.exit_code is not None else -1
    out_pair = exec_result.output
    # With ``demux=True`` and no streaming, exec_run returns (stdout, stderr)
    # of ``bytes | None`` each. The other overloads (bytes, iterator) only
    # apply with different params, but we guard structurally for safety.
    stdout: bytes = b""
    stderr: bytes = b""
    if isinstance(out_pair, tuple):
        stdout_raw, stderr_raw = out_pair
        if isinstance(stdout_raw, bytes):
            stdout = stdout_raw
        if isinstance(stderr_raw, bytes):
            stderr = stderr_raw
    elif isinstance(out_pair, bytes):
        stdout = out_pair

    if check and exit_code != 0:
        raise ExecError(
            f"command {_command_summary(command)} exited with {exit_code}: "
            f"{stderr.decode('utf-8', errors='replace').strip()}",
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
        )

    return ExecResult(exit_code=exit_code, stdout=stdout, stderr=stderr)


def stream_stdin_to_container(
    container: Container,
    command: list[str],
    payload: bytes,
    *,
    user: str | None = None,
    workdir: str | None = None,
) -> ExecResult:
    """Run ``command`` inside ``container`` and stream ``payload`` into stdin.

    Used to push tar archives and snapshot bytes into the sandbox via a
    remote ``tar -x`` / ``head -c N | tar -x`` pipeline without staging the
    bytes on disk inside the api_server.
    """
    if container.client is None:
        raise ExecError("docker client unavailable on container")
    api = container.client.api
    try:
        exec_id = api.exec_create(
            container.id,
            cmd=command,
            stdin=True,
            stdout=True,
            stderr=True,
            tty=False,
            user=user or "",
            workdir=workdir,
        )["Id"]
        sock = api.exec_start(exec_id, socket=True, demux=False)
    except (APIError, NotFound) as e:
        raise ExecError(f"exec_create failed: {e}") from e

    raw_sock = _unwrap_socket(sock)
    try:
        raw_sock.sendall(payload)
        # Half-close write side so the remote process sees EOF.
        try:
            raw_sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass

        stdout, stderr = _drain_multiplexed_stream(raw_sock)
    finally:
        try:
            raw_sock.close()
        except OSError:
            pass

    try:
        info = api.exec_inspect(exec_id)
    except APIError as e:
        raise ExecError(f"exec_inspect failed: {e}") from e

    exit_code = info.get("ExitCode")
    if exit_code is None:
        exit_code = -1
    if exit_code != 0:
        raise ExecError(
            f"stdin-stream command {_command_summary(command)} exited with "
            f"{exit_code}: {stderr.decode('utf-8', errors='replace').strip()}",
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
        )
    return ExecResult(exit_code=exit_code, stdout=stdout, stderr=stderr)


def stream_stdout_from_container(
    container: Container,
    command: list[str],
    *,
    user: str | None = None,
    workdir: str | None = None,
    chunk_size: int = 64 * 1024,
) -> Generator[bytes, None, int]:
    """Run ``command`` and yield stdout chunks to the caller.

    Generator returns the process exit code via ``StopIteration.value``. The
    caller is responsible for consuming until exhaustion to ensure cleanup.

    Used to stream tar bytes out of the sandbox container for snapshots.
    """
    if container.client is None:
        raise ExecError("docker client unavailable on container")
    api = container.client.api
    try:
        exec_id = api.exec_create(
            container.id,
            cmd=command,
            stdin=False,
            stdout=True,
            stderr=True,
            tty=False,
            user=user or "",
            workdir=workdir,
        )["Id"]
        sock = api.exec_start(exec_id, socket=True, demux=False)
    except (APIError, NotFound) as e:
        raise ExecError(f"exec_create failed: {e}") from e

    raw_sock = _unwrap_socket(sock)
    stderr_buf = bytearray()
    try:
        for frame_type, frame in _iter_frames(raw_sock, chunk_size=chunk_size):
            if frame_type == _FRAME_STDOUT:
                if frame:
                    yield frame
            elif frame_type == _FRAME_STDERR:
                stderr_buf.extend(frame)
    finally:
        try:
            raw_sock.close()
        except OSError:
            pass

    try:
        info = api.exec_inspect(exec_id)
    except APIError as e:
        raise ExecError(f"exec_inspect failed: {e}") from e

    exit_code = info.get("ExitCode")
    if exit_code is None:
        exit_code = -1
    if exit_code != 0:
        raise ExecError(
            f"stdout-stream command {_command_summary(command)} exited with "
            f"{exit_code}: "
            f"{bytes(stderr_buf).decode('utf-8', errors='replace').strip()}",
            exit_code=exit_code,
            stdout=b"",
            stderr=bytes(stderr_buf),
        )
    return exit_code


def _unwrap_socket(sock: object) -> socket.socket:
    """Get the raw socket underneath docker SDK's SocketIO wrapper."""
    raw = getattr(sock, "_sock", None)
    if isinstance(raw, socket.socket):
        return raw
    if isinstance(sock, socket.socket):
        return sock
    raise ExecError(f"Could not unwrap docker exec socket of type {type(sock)!r}")


def _read_exact(sock: socket.socket, n: int) -> bytes:
    """Read exactly ``n`` bytes from ``sock`` or return what's available on EOF."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            break
        buf.extend(chunk)
    return bytes(buf)


def _iter_frames(
    sock: socket.socket, *, chunk_size: int
) -> Generator[tuple[int, bytes], None, None]:
    """Iterate (stream_type, payload) frames from a docker multiplexed stream."""
    while True:
        header = _read_exact(sock, _FRAME_HEADER_BYTES)
        if not header:
            return
        if len(header) < _FRAME_HEADER_BYTES:
            # Truncated header — bail rather than misinterpret bytes.
            return
        stream_type = header[0]
        (length,) = struct.unpack(">I", header[4:8])
        remaining = length
        while remaining > 0:
            chunk = sock.recv(min(remaining, chunk_size))
            if not chunk:
                return
            yield stream_type, chunk
            remaining -= len(chunk)


def _drain_multiplexed_stream(sock: socket.socket) -> tuple[bytes, bytes]:
    """Consume a docker multiplexed stream into separate stdout/stderr buffers."""
    stdout_buf = bytearray()
    stderr_buf = bytearray()
    for stream_type, frame in _iter_frames(sock, chunk_size=64 * 1024):
        if stream_type == _FRAME_STDOUT:
            stdout_buf.extend(frame)
        elif stream_type == _FRAME_STDERR:
            stderr_buf.extend(frame)
    return bytes(stdout_buf), bytes(stderr_buf)
