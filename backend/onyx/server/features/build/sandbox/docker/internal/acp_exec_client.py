"""ACP client that communicates via ``docker exec`` into the sandbox container.

This is the Docker analogue of
``onyx.server.features.build.sandbox.kubernetes.internal.acp_exec_client``.
The shared JSON-RPC protocol lives on :class:`ACPExecClientBase`; this
subclass owns the multiplexed-docker-exec transport.

Each message creates an ephemeral client (start → resume_or_create_session →
send_message → stop) so only a single ``opencode`` process ever operates on
a session's flat-file storage at a time.
"""

from __future__ import annotations

import json
import shlex
import socket
import struct
import threading
from typing import Any
from typing import ClassVar

from docker import DockerClient
from docker.errors import APIError
from docker.errors import NotFound

from onyx.server.features.build.sandbox.acp.base import ACPExecClientBase
from onyx.server.features.build.sandbox.docker.internal.exec_helpers import (
    _FRAME_HEADER_BYTES,
)
from onyx.server.features.build.sandbox.docker.internal.exec_helpers import (
    _FRAME_STDERR,
)
from onyx.server.features.build.sandbox.docker.internal.exec_helpers import (
    _FRAME_STDOUT,
)
from onyx.server.features.build.sandbox.docker.internal.exec_helpers import (
    _unwrap_socket,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


DEFAULT_CLIENT_INFO = {
    "name": "onyx-sandbox-docker-exec",
    "title": "Onyx Sandbox Agent Client (Docker Exec)",
    "version": "1.0.0",
}


class DockerACPExecClient(ACPExecClientBase):
    """ACP client that talks JSON-RPC over a ``docker exec`` socket."""

    transport_name: ClassVar[str] = "docker"

    def __init__(
        self,
        docker_client: DockerClient,
        container_name: str,
        *,
        user: str = "1000:1000",
        client_info: dict[str, Any] | None = None,
        client_capabilities: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            client_info=client_info or DEFAULT_CLIENT_INFO,
            client_capabilities=client_capabilities,
        )
        self._docker = docker_client
        self._container_name = container_name
        self._user = user
        self._exec_id: str | None = None
        self._socket: socket.socket | None = None
        self._socket_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Transport hooks
    # ------------------------------------------------------------------

    def _log_target(self) -> str:
        return f"container={self._container_name}"

    def _open_transport(self, cwd: str) -> None:
        data_dir = shlex.quote(f"{cwd}/.opencode-data")
        safe_cwd = shlex.quote(cwd)
        cmd = [
            "/bin/sh",
            "-c",
            f"XDG_DATA_HOME={data_dir} exec opencode acp --cwd {safe_cwd}",
        ]

        try:
            api = self._docker.api
            exec_info = api.exec_create(
                self._container_name,
                cmd=cmd,
                stdin=True,
                stdout=True,
                stderr=True,
                tty=False,
                user=self._user,
            )
            self._exec_id = exec_info["Id"]
            wrapped_sock = api.exec_start(self._exec_id, socket=True, demux=False)
            self._socket = _unwrap_socket(wrapped_sock)
            # Make recv() return promptly so the reader can poll for shutdown.
            self._socket.settimeout(0.5)
        except (APIError, NotFound) as e:
            raise RuntimeError(f"docker exec failed: {e}") from e

    def _close_transport(self) -> None:
        if self._socket is not None:
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None
        self._exec_id = None

    def _is_transport_open(self) -> bool:
        return self._socket is not None

    def _write_line(self, line: str) -> None:
        sock = self._socket
        if sock is None:
            raise RuntimeError("Docker exec socket not open")
        with self._socket_lock:
            sock.sendall(line.encode("utf-8"))

    def _read_responses_loop(self) -> None:
        """Parse multiplexed docker-exec frames into JSON-RPC messages."""
        buffer = ""

        while not self._stop_reader.is_set():
            sock = self._socket
            if sock is None:
                return
            try:
                header = self._recv_exact(sock, _FRAME_HEADER_BYTES)
            except socket.timeout:
                continue
            except OSError:
                return
            if not header or len(header) < _FRAME_HEADER_BYTES:
                return

            stream_type = header[0]
            (length,) = struct.unpack(">I", header[4:8])
            if length == 0:
                continue
            try:
                payload = self._recv_exact(sock, length)
            except (socket.timeout, OSError):
                return
            if not payload:
                return

            if stream_type == _FRAME_STDERR:
                logger.warning(
                    "%s stderr %s: %s",
                    self._log_prefix,
                    self._log_target(),
                    payload.decode("utf-8", errors="replace").strip()[:500],
                )
                continue
            if stream_type != _FRAME_STDOUT:
                continue

            buffer += payload.decode("utf-8", errors="replace")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning(
                        "%s Invalid JSON from agent: %s",
                        self._log_prefix,
                        line[:100],
                    )
                    continue
                self._enqueue_message(message)

    def _recv_exact(self, sock: socket.socket, n: int) -> bytes:
        """Read exactly ``n`` bytes, retrying through ``socket.timeout``.

        The socket has a short read timeout (set in ``_open_transport``) so
        the reader thread can periodically check ``_stop_reader`` for
        shutdown. That timeout must NOT be allowed to discard partial bytes
        mid-frame — Docker's multiplexed exec stream sends a fixed 8-byte
        header followed by ``length`` bytes of payload, and if we drop 3
        of those 8 header bytes the next read interprets the remaining 5
        as the start of a new header, corrupting all downstream framing.

        Returns partial data (``len < n``) only on EOF or shutdown.
        """
        buf = bytearray()
        while len(buf) < n:
            if self._stop_reader.is_set():
                return bytes(buf)
            try:
                chunk = sock.recv(n - len(buf))
            except socket.timeout:
                # Re-check shutdown then keep reading from where we are.
                # Critical: we must NOT discard ``buf`` here.
                continue
            if not chunk:
                return bytes(buf)
            buf.extend(chunk)
        return bytes(buf)
