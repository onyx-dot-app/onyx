"""ACP client that communicates via ``docker exec`` into the sandbox container.

This is the Docker analogue of
``onyx.server.features.build.sandbox.kubernetes.internal.acp_exec_client``.

It runs ``opencode acp`` inside the sandbox container via the Docker Engine
exec API and shuttles JSON-RPC messages between api_server and the agent
over the multiplexed exec stream.

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
import time
from collections.abc import Generator
from dataclasses import dataclass
from dataclasses import field
from queue import Empty
from queue import Queue
from typing import Any
from typing import cast

from acp.schema import AgentMessageChunk
from acp.schema import AgentPlanUpdate
from acp.schema import AgentThoughtChunk
from acp.schema import CurrentModeUpdate
from acp.schema import Error
from acp.schema import PromptResponse
from acp.schema import ToolCallProgress
from acp.schema import ToolCallStart
from docker import DockerClient
from docker.errors import APIError
from docker.errors import NotFound
from pydantic import BaseModel
from pydantic import ValidationError

from onyx.server.features.build.api.packet_logger import get_packet_logger
from onyx.server.features.build.configs import ACP_MESSAGE_TIMEOUT
from onyx.server.features.build.configs import SSE_KEEPALIVE_INTERVAL
from onyx.server.features.build.sandbox.base import SSEKeepalive as SSEKeepalive
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

ACP_PROTOCOL_VERSION = 1

DEFAULT_CLIENT_INFO = {
    "name": "onyx-sandbox-docker-exec",
    "title": "Onyx Sandbox Agent Client (Docker Exec)",
    "version": "1.0.0",
}

# Header for docker multiplexed exec streams.
_FRAME_HEADER_BYTES = 8


ACPEvent = (
    AgentMessageChunk
    | AgentThoughtChunk
    | ToolCallStart
    | ToolCallProgress
    | AgentPlanUpdate
    | CurrentModeUpdate
    | PromptResponse
    | Error
    | SSEKeepalive
)


@dataclass
class ACPSession:
    session_id: str
    cwd: str


@dataclass
class ACPClientState:
    initialized: bool = False
    sessions: dict[str, ACPSession] = field(default_factory=dict)
    next_request_id: int = 0
    agent_capabilities: dict[str, Any] = field(default_factory=dict)
    agent_info: dict[str, Any] = field(default_factory=dict)


class DockerACPExecClient:
    """ACP client that talks JSON-RPC over a ``docker exec`` socket.

    Mirrors the K8s ``ACPExecClient`` but uses the Docker Engine API for
    process management.
    """

    def __init__(
        self,
        docker_client: DockerClient,
        container_name: str,
        *,
        user: str = "1000:1000",
        client_info: dict[str, Any] | None = None,
        client_capabilities: dict[str, Any] | None = None,
    ) -> None:
        self._docker = docker_client
        self._container_name = container_name
        self._user = user
        self._client_info = client_info or DEFAULT_CLIENT_INFO
        self._client_capabilities = client_capabilities or {
            "fs": {"readTextFile": True, "writeTextFile": True},
            "terminal": True,
        }
        self._state = ACPClientState()
        self._exec_id: str | None = None
        self._socket: socket.socket | None = None
        self._socket_lock = threading.Lock()
        self._response_queue: Queue[dict[str, Any]] = Queue()
        self._reader_thread: threading.Thread | None = None
        self._stop_reader = threading.Event()

    def start(self, cwd: str = "/workspace", timeout: float = 30.0) -> None:
        """Start ``opencode acp`` in the sandbox container and ACP-initialize."""
        if self._socket is not None:
            raise RuntimeError("Client already started. Call stop() first.")

        data_dir = shlex.quote(f"{cwd}/.opencode-data")
        safe_cwd = shlex.quote(cwd)
        cmd = [
            "/bin/sh",
            "-c",
            f"XDG_DATA_HOME={data_dir} exec opencode acp --cwd {safe_cwd}",
        ]

        logger.info(
            "[DOCKER-ACP] Starting client: container=%s cwd=%s",
            self._container_name,
            cwd,
        )

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

            self._stop_reader.clear()
            self._reader_thread = threading.Thread(
                target=self._read_responses, daemon=True
            )
            self._reader_thread.start()

            # Let opencode boot before sending the initialize.
            time.sleep(0.5)
            self._initialize(timeout=timeout)
            logger.info(
                "[DOCKER-ACP] Client started: container=%s", self._container_name
            )
        except (APIError, NotFound) as e:
            logger.error(
                "[DOCKER-ACP] start failed: container=%s err=%s",
                self._container_name,
                e,
            )
            self.stop()
            raise RuntimeError(f"Failed to start docker ACP exec client: {e}") from e
        except Exception:
            self.stop()
            raise

    def _read_responses(self) -> None:
        """Background thread: parse multiplexed frames into JSON-RPC messages."""
        buffer = ""
        packet_logger = get_packet_logger()

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
                    "[DOCKER-ACP] stderr container=%s: %s",
                    self._container_name,
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
                        "[DOCKER-ACP] Invalid JSON from agent: %s", line[:100]
                    )
                    continue
                packet_logger.log_jsonrpc_raw_message("IN", message, context="docker")
                self._response_queue.put(message)

    def _recv_exact(self, sock: socket.socket, n: int) -> bytes:
        """Read exactly ``n`` bytes, retrying through ``socket.timeout``.

        The socket has a short read timeout (set in ``start``) so the reader
        thread can periodically check ``_stop_reader`` for shutdown. That
        timeout must NOT be allowed to discard partial bytes mid-frame —
        Docker's multiplexed exec stream sends a fixed 8-byte header followed
        by ``length`` bytes of payload, and if we drop 3 of those 8 header
        bytes the next read interprets the remaining 5 as the start of a new
        header, corrupting all downstream framing.

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

    def stop(self) -> None:
        session_ids = list(self._state.sessions.keys())
        logger.info(
            "[DOCKER-ACP] Stopping client: container=%s sessions=%s",
            self._container_name,
            session_ids,
        )
        self._stop_reader.set()

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

        if self._reader_thread is not None:
            self._reader_thread.join(timeout=2.0)
            self._reader_thread = None

        self._exec_id = None
        self._state = ACPClientState()

    def _get_next_id(self) -> int:
        request_id = self._state.next_request_id
        self._state.next_request_id += 1
        return request_id

    def _send_raw(self, line: str) -> None:
        if self._socket is None:
            raise RuntimeError("Docker exec socket not open")
        with self._socket_lock:
            self._socket.sendall(line.encode("utf-8"))

    def _send_request(self, method: str, params: dict[str, Any] | None = None) -> int:
        request_id = self._get_next_id()
        request: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            request["params"] = params

        packet_logger = get_packet_logger()
        packet_logger.log_jsonrpc_request(method, request_id, params, context="docker")
        self._send_raw(json.dumps(request) + "\n")
        return request_id

    def _send_notification(
        self, method: str, params: dict[str, Any] | None = None
    ) -> None:
        if self._socket is None:
            return
        notification: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            notification["params"] = params
        packet_logger = get_packet_logger()
        packet_logger.log_jsonrpc_request(method, None, params, context="docker")
        try:
            self._send_raw(json.dumps(notification) + "\n")
        except OSError:
            return

    def _wait_for_response(
        self, request_id: int, timeout: float = 30.0
    ) -> dict[str, Any]:
        start_time = time.time()
        while True:
            remaining = timeout - (time.time() - start_time)
            if remaining <= 0:
                raise RuntimeError(
                    f"Timeout waiting for response to request {request_id}"
                )
            try:
                message = self._response_queue.get(timeout=min(remaining, 1.0))
                if message.get("id") == request_id:
                    if "error" in message:
                        error = message["error"]
                        raise RuntimeError(
                            f"ACP error {error.get('code')}: {error.get('message')}"
                        )
                    return message.get("result", {})
                self._response_queue.put(message)
            except Empty:
                continue

    def _initialize(self, timeout: float = 30.0) -> dict[str, Any]:
        params = {
            "protocolVersion": ACP_PROTOCOL_VERSION,
            "clientCapabilities": self._client_capabilities,
            "clientInfo": self._client_info,
        }
        request_id = self._send_request("initialize", params)
        result = self._wait_for_response(request_id, timeout)
        self._state.initialized = True
        self._state.agent_capabilities = result.get("agentCapabilities", {})
        self._state.agent_info = result.get("agentInfo", {})
        return result

    def _create_session(self, cwd: str, timeout: float = 30.0) -> str:
        params = {"cwd": cwd, "mcpServers": []}
        request_id = self._send_request("session/new", params)
        result = self._wait_for_response(request_id, timeout)
        session_id = result.get("sessionId")
        if not session_id:
            raise RuntimeError("No session ID returned from session/new")
        self._state.sessions[session_id] = ACPSession(session_id=session_id, cwd=cwd)
        logger.info(
            "[DOCKER-ACP] Created session: acp_session=%s cwd=%s", session_id, cwd
        )
        return session_id

    def _list_sessions(self, cwd: str, timeout: float = 10.0) -> list[dict[str, Any]]:
        try:
            request_id = self._send_request("session/list", {"cwd": cwd})
            result = self._wait_for_response(request_id, timeout)
            return cast("list[dict[str, Any]]", result.get("sessions", []))
        except Exception as e:
            logger.info("[DOCKER-ACP] session/list unavailable: %s", e)
            return []

    def _resume_session(self, session_id: str, cwd: str, timeout: float = 30.0) -> str:
        params = {"sessionId": session_id, "cwd": cwd, "mcpServers": []}
        request_id = self._send_request("session/resume", params)
        result = self._wait_for_response(request_id, timeout)
        resumed_id = result.get("sessionId", session_id)
        self._state.sessions[resumed_id] = ACPSession(session_id=resumed_id, cwd=cwd)
        logger.info(
            "[DOCKER-ACP] Resumed session: acp_session=%s cwd=%s", resumed_id, cwd
        )
        return resumed_id

    def _try_resume_existing_session(self, cwd: str, timeout: float) -> str | None:
        sessions = self._list_sessions(cwd, timeout=min(timeout, 10.0))
        if not sessions:
            return None
        target = sessions[0]
        target_id = target.get("sessionId")
        if not target_id:
            return None
        try:
            return self._resume_session(target_id, cwd, timeout)
        except Exception as e:
            logger.warning(
                "[DOCKER-ACP] session/resume failed for %s: %s, falling back to session/new",
                target_id,
                e,
            )
            return None

    def resume_or_create_session(self, cwd: str, timeout: float = 30.0) -> str:
        if not self._state.initialized:
            raise RuntimeError("Client not initialized. Call start() first.")
        resumed_id = self._try_resume_existing_session(cwd, timeout)
        if resumed_id:
            return resumed_id
        return self._create_session(cwd=cwd, timeout=timeout)

    def send_message(
        self,
        message: str,
        session_id: str,
        timeout: float = ACP_MESSAGE_TIMEOUT,
    ) -> Generator[ACPEvent, None, None]:
        if session_id not in self._state.sessions:
            raise RuntimeError(
                f"Unknown session {session_id}. "
                f"Known: {list(self._state.sessions.keys())}"
            )
        packet_logger = get_packet_logger()

        prompt_content = [{"type": "text", "text": message}]
        params = {"sessionId": session_id, "prompt": prompt_content}
        request_id = self._send_request("session/prompt", params)
        start_time = time.time()
        last_event_time = time.time()
        events_yielded = 0
        completion_reason = "unknown"

        while True:
            remaining = timeout - (time.time() - start_time)
            if remaining <= 0:
                completion_reason = "timeout"
                logger.warning(
                    "[DOCKER-ACP] Prompt timeout: acp_session=%s events=%s",
                    session_id,
                    events_yielded,
                )
                try:
                    self.cancel(session_id=session_id)
                except Exception as cancel_err:
                    logger.warning(
                        "[DOCKER-ACP] session/cancel failed on timeout: %s", cancel_err
                    )
                yield Error(code=-1, message="Timeout waiting for response")
                break

            try:
                message_data = self._response_queue.get(timeout=min(remaining, 1.0))
                last_event_time = time.time()
            except Empty:
                idle_time = time.time() - last_event_time
                if idle_time >= SSE_KEEPALIVE_INTERVAL:
                    yield SSEKeepalive()
                    last_event_time = time.time()
                continue

            msg_id = message_data.get("id")
            is_response = "method" not in message_data and (
                msg_id == request_id
                or (msg_id is not None and str(msg_id) == str(request_id))
            )
            if is_response:
                completion_reason = "jsonrpc_response"
                if "error" in message_data:
                    error_data = message_data["error"]
                    completion_reason = "jsonrpc_error"
                    packet_logger.log_jsonrpc_response(
                        request_id, error=error_data, context="docker"
                    )
                    yield Error(
                        code=error_data.get("code", -1),
                        message=error_data.get("message", "Unknown error"),
                    )
                else:
                    result = message_data.get("result", {})
                    packet_logger.log_jsonrpc_response(
                        request_id, result=result, context="docker"
                    )
                    try:
                        prompt_response = PromptResponse.model_validate(result)
                        events_yielded += 1
                        yield prompt_response
                    except ValidationError as e:
                        logger.error(
                            "[DOCKER-ACP] PromptResponse validation failed: %s", e
                        )
                elapsed_ms = (time.time() - start_time) * 1000
                logger.info(
                    "[DOCKER-ACP] Prompt complete: reason=%s acp_session=%s events=%s elapsed=%sms",
                    completion_reason,
                    session_id,
                    events_yielded,
                    format(elapsed_ms, ".0f"),
                )
                break

            if message_data.get("method") == "session/update":
                params_data = message_data.get("params", {})
                update = params_data.get("update", {})
                prompt_complete = False
                for event in self._process_session_update(update):
                    events_yielded += 1
                    yield event
                    if isinstance(event, PromptResponse):
                        prompt_complete = True
                        break
                if prompt_complete:
                    completion_reason = "prompt_response_via_notification"
                    break

            elif "method" in message_data and "id" in message_data:
                self._send_error_response(
                    message_data["id"],
                    -32601,
                    f"Method not supported: {message_data['method']}",
                )

    def _process_session_update(
        self, update: dict[str, Any]
    ) -> Generator[ACPEvent, None, None]:
        update_type = update.get("sessionUpdate")
        if not isinstance(update_type, str):
            return
        type_map: dict[str, type[BaseModel]] = {
            "agent_message_chunk": AgentMessageChunk,
            "agent_thought_chunk": AgentThoughtChunk,
            "tool_call": ToolCallStart,
            "tool_call_update": ToolCallProgress,
            "plan": AgentPlanUpdate,
            "current_mode_update": CurrentModeUpdate,
            "prompt_response": PromptResponse,
        }
        model_class = type_map.get(update_type)
        if model_class is not None:
            try:
                yield cast(ACPEvent, model_class.model_validate(update))
            except ValidationError as e:
                logger.warning(
                    "[DOCKER-ACP] Validation error for %s: %s", update_type, e
                )

    def _send_error_response(self, request_id: int, code: int, message: str) -> None:
        if self._socket is None:
            return
        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }
        try:
            self._send_raw(json.dumps(response) + "\n")
        except OSError:
            return

    def cancel(self, session_id: str | None = None) -> None:
        if session_id:
            if session_id in self._state.sessions:
                self._send_notification("session/cancel", {"sessionId": session_id})
        else:
            for sid in list(self._state.sessions):
                self._send_notification("session/cancel", {"sessionId": sid})

    @property
    def is_running(self) -> bool:
        return self._socket is not None

    def __enter__(self) -> "DockerACPExecClient":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()
