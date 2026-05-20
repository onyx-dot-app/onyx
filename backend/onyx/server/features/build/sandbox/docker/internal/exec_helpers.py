"""Shared docker exec primitives for the Docker sandbox backend.

Three primitives wrap ``docker.client.containers.Container.exec_run`` and
its lower-level ``exec_create`` / ``exec_start`` cousins:

- ``run_in_container``: capture stdout/stderr/exit code from a one-shot exec.
- ``stream_stdin_to_container``: pipe bytes into a remote process's stdin.
- ``stream_stdout_from_container``: stream a remote process's stdout back
  (used by snapshot creation, where we don't want to spool to disk).

All helpers raise :class:`ExecError` on non-zero exit or transport failure.
Callers translate to ``RuntimeError`` / write-error types as appropriate.
"""

from __future__ import annotations

import socket
import struct
from collections.abc import Generator
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from docker.errors import APIError
from docker.errors import NotFound
from docker.models.containers import Container

from onyx.utils.logger import setup_logger

logger = setup_logger()


# Docker multiplexed exec stream frame header is 8 bytes:
#   byte 0: stream type (1=stdout, 2=stderr)
#   bytes 1-3: zero padding
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
    """Raised when a docker exec invocation fails."""


def _command_summary(command: list[str] | str) -> str:
    """Render a command for error messages without leaking inlined secrets.

    Setup scripts embed ``printf '%s' '<opencode.json>' > ...`` where the
    JSON includes the LLM API key. Including the full script in an exception
    message would leak that key into api_server logs on any setup failure.
    Long argv elements get replaced with a length-tagged placeholder.
    """
    if isinstance(command, str):
        return (
            repr(command)
            if len(command) <= 200
            else f"<shell script: {len(command)} bytes>"
        )
    summarized = [
        f"<shell script: {len(arg)} bytes>"
        if isinstance(arg, str) and len(arg) > 200
        else arg
        for arg in command
    ]
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

    Wraps ``Container.exec_run`` with ``demux=True`` so stdout/stderr are
    returned as separate byte strings. Raises :class:`ExecError` on non-zero
    exit when ``check=True`` (default).
    """
    try:
        result = container.exec_run(
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

    exit_code = result.exit_code if result.exit_code is not None else -1
    # ``demux=True`` documents a ``(stdout_bytes_or_none, stderr_bytes_or_none)``
    # tuple; the SDK's overloaded return type confuses ty into thinking it
    # could also be ``bytes`` or ``Iterator[bytes]`` (those apply for other
    # parameter combinations). Structural guard for safety + readability.
    out_pair = result.output
    stdout, stderr = b"", b""
    if isinstance(out_pair, tuple) and len(out_pair) == 2:
        stdout = out_pair[0] if isinstance(out_pair[0], bytes) else b""
        stderr = out_pair[1] if isinstance(out_pair[1], bytes) else b""

    if check and exit_code != 0:
        raise ExecError(
            f"command {_command_summary(command)} exited with {exit_code}: "
            f"{stderr.decode('utf-8', errors='replace').strip()}"
        )
    return ExecResult(exit_code=exit_code, stdout=stdout, stderr=stderr)


@contextmanager
def _open_exec_socket(
    container: Container,
    command: list[str],
    *,
    stdin: bool,
    user: str | None,
    workdir: str | None,
) -> Iterator[tuple[str, socket.socket]]:
    """Create + start a docker exec and yield ``(exec_id, raw_socket)``.

    The high-level ``Container.exec_run`` doesn't expose a raw socket, so
    snapshot tar streaming has to go through the low-level ``APIClient``.
    """
    if container.client is None:
        raise ExecError("docker client unavailable on container")
    api = container.client.api
    try:
        exec_id = api.exec_create(
            container.id,
            cmd=command,
            stdin=stdin,
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
        yield exec_id, raw_sock
    finally:
        try:
            raw_sock.close()
        except OSError:
            pass


def _check_exit(
    container: Container, exec_id: str, command: list[str], stderr: bytes
) -> int:
    """Read the exec's exit code; raise ExecError on non-zero."""
    if container.client is None:
        raise ExecError("docker client unavailable on container")
    try:
        info = container.client.api.exec_inspect(exec_id)
    except APIError as e:
        raise ExecError(f"exec_inspect failed: {e}") from e
    exit_code = info.get("ExitCode")
    if exit_code is None:
        exit_code = -1
    if exit_code != 0:
        raise ExecError(
            f"command {_command_summary(command)} exited with {exit_code}: "
            f"{stderr.decode('utf-8', errors='replace').strip()}"
        )
    return exit_code


def stream_stdin_to_container(
    container: Container,
    command: list[str],
    payload: bytes,
    *,
    user: str | None = None,
    workdir: str | None = None,
) -> ExecResult:
    """Run ``command`` inside ``container`` and feed ``payload`` to its stdin.

    Used for tar push (skills + user library) and snapshot restore.
    """
    with _open_exec_socket(
        container, command, stdin=True, user=user, workdir=workdir
    ) as (exec_id, sock):
        sock.sendall(payload)
        # Half-close so the remote process sees EOF.
        try:
            sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass

        stdout_buf = bytearray()
        stderr_buf = bytearray()
        for stream_type, frame in _iter_frames(sock, chunk_size=64 * 1024):
            if stream_type == _FRAME_STDOUT:
                stdout_buf.extend(frame)
            elif stream_type == _FRAME_STDERR:
                stderr_buf.extend(frame)

    stderr = bytes(stderr_buf)
    exit_code = _check_exit(container, exec_id, command, stderr)
    return ExecResult(exit_code=exit_code, stdout=bytes(stdout_buf), stderr=stderr)


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
    Used to stream tar bytes out of the sandbox for snapshots.
    """
    stderr_buf = bytearray()
    with _open_exec_socket(
        container, command, stdin=False, user=user, workdir=workdir
    ) as (exec_id, sock):
        for stream_type, frame in _iter_frames(sock, chunk_size=chunk_size):
            if stream_type == _FRAME_STDOUT and frame:
                yield frame
            elif stream_type == _FRAME_STDERR:
                stderr_buf.extend(frame)

    return _check_exit(container, exec_id, command, bytes(stderr_buf))


def _unwrap_socket(sock: object) -> socket.socket:
    """Get the raw socket underneath docker SDK's SocketIO wrapper."""
    raw = getattr(sock, "_sock", None)
    if isinstance(raw, socket.socket):
        return raw
    if isinstance(sock, socket.socket):
        return sock
    raise ExecError(f"Could not unwrap docker exec socket of type {type(sock)!r}")


def _iter_frames(
    sock: socket.socket, *, chunk_size: int
) -> Generator[tuple[int, bytes], None, None]:
    """Iterate (stream_type, payload) frames from a docker multiplexed stream."""
    while True:
        header = _read_exact(sock, _FRAME_HEADER_BYTES)
        if len(header) < _FRAME_HEADER_BYTES:
            return  # clean EOF or truncation — bail rather than misframe
        stream_type = header[0]
        (length,) = struct.unpack(">I", header[4:8])
        remaining = length
        while remaining > 0:
            chunk = sock.recv(min(remaining, chunk_size))
            if not chunk:
                return
            yield stream_type, chunk
            remaining -= len(chunk)


def _read_exact(sock: socket.socket, n: int) -> bytes:
    """Read exactly ``n`` bytes, or return what's available on EOF."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            break
        buf.extend(chunk)
    return bytes(buf)
