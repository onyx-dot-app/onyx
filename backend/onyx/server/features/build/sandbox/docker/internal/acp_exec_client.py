"""ACP client that communicates via ``docker exec`` into the sandbox container.

Mirrors ``backend/onyx/server/features/build/sandbox/kubernetes/internal/acp_exec_client.py``
in shape: starts ``opencode acp`` in the container, speaks JSON-RPC over
stdin/stdout, runs a reader thread that drains the stream, and exposes the
same ``start`` / ``resume_or_create_session`` / ``send_message`` / ``stop`` /
``cancel`` / ``health_check`` surface used by the Docker manager.

The transport is the only difference. Where K8s uses
``kubernetes.stream.stream(... connect_get_namespaced_pod_exec ...)`` and
treats the resulting WebSocket as a JSON-RPC pipe, here we use
``client.api.exec_create(...)`` + ``client.api.exec_start(socket=True)`` to
obtain a duplex socket. Frames on that socket are stream-multiplexed (when
the exec is created with ``tty=False``), so we strip the 8-byte framing
header before passing payload bytes to the JSON-RPC parser.
"""

from __future__ import annotations

import json
import shlex
import socket as socketlib
import threading
import time
from collections.abc import Generator
from dataclasses import dataclass
from dataclasses import field
from queue import Empty
from queue import Queue
from typing import Any
from typing import cast

import docker  # type: ignore[import-untyped]
from acp.schema import AgentMessageChunk
from acp.schema import AgentPlanUpdate
from acp.schema import AgentThoughtChunk
from acp.schema import CurrentModeUpdate
from acp.schema import Error
from acp.schema import PromptResponse
from acp.schema import ToolCallProgress
from acp.schema import ToolCallStart
from docker.errors import NotFound  # type: ignore[import-untyped]
from pydantic import BaseModel
from pydantic import ValidationError

from onyx.server.features.build.api.packet_logger import get_packet_logger
from onyx.server.features.build.configs import ACP_MESSAGE_TIMEOUT
from onyx.server.features.build.configs import SSE_KEEPALIVE_INTERVAL
from onyx.utils.logger import setup_logger

logger = setup_logger()

ACP_PROTOCOL_VERSION = 1

DEFAULT_CLIENT_INFO = {
    "name": "onyx-sandbox-docker-exec",
    "title": "Onyx Sandbox Agent Client (Docker Exec)",
    "version": "1.0.0",
}


@dataclass
class SSEKeepalive:
    """Marker yielded when the prompt has been idle too long for SSE.

    Same shape as the K8s client's marker so the upstream consumer doesn't
    need to know which backend produced the stream.
    """


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


class _DemuxBuffer:
    """Stateful demuxer for the Docker stream-multiplexing framing.

    Feed raw bytes via ``feed()``; iterate ``drain_stdout()`` / ``drain_stderr()``
    to consume the demultiplexed payloads. The buffer keeps any trailing bytes
    that don't yet form a complete frame.
    """

    def __init__(self) -> None:
        self._buf = bytearray()
        self._stdout = bytearray()
        self._stderr = bytearray()

    def feed(self, data: bytes) -> None:
        self._buf.extend(data)
        self._parse()

    def _parse(self) -> None:
        i = 0
        n = len(self._buf)
        while i + 8 <= n:
            header = self._buf[i : i + 8]
            stream_type = header[0]
            size = int.from_bytes(bytes(header[4:8]), "big")
            if i + 8 + size > n:
                break
            payload = self._buf[i + 8 : i + 8 + size]
            if stream_type == 1:
                self._stdout.extend(payload)
            elif stream_type == 2:
                self._stderr.extend(payload)
            else:
                # unknown stream id, treat as stdout to avoid losing data
                self._stdout.extend(payload)
            i += 8 + size
        if i > 0:
            del self._buf[:i]

    def drain_stdout(self) -> bytes:
        out = bytes(self._stdout)
        self._stdout.clear()
        return out

    def drain_stderr(self) -> bytes:
        out = bytes(self._stderr)
        self._stderr.clear()
        return out


class ACPExecClient:
    """ACP client that talks to ``opencode acp`` over a docker exec socket.

    Public surface mirrors ``kubernetes/internal/acp_exec_client.ACPExecClient``
    so the Docker manager can swap the import without touching call sites.
    """

    def __init__(
        self,
        container_name: str,
        docker_client: docker.DockerClient,
        client_info: dict[str, Any] | None = None,
        client_capabilities: dict[str, Any] | None = None,
    ) -> None:
        self._container_name = container_name
        self._docker = docker_client
        self._client_info = client_info or DEFAULT_CLIENT_INFO
        self._client_capabilities = client_capabilities or {
            "fs": {"readTextFile": True, "writeTextFile": True},
            "terminal": True,
        }
        self._state = ACPClientState()
        self._exec_id: str | None = None
        self._socket: Any | None = None  # the SDK's socket wrapper
        self._raw_sock: socketlib.socket | None = None
        self._response_queue: Queue[dict[str, Any]] = Queue()
        self._reader_thread: threading.Thread | None = None
        self._stop_reader = threading.Event()
        self._send_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self, cwd: str = "/workspace", timeout: float = 30.0) -> None:
        if self._exec_id is not None:
            raise RuntimeError("Client already started. Call stop() first.")

        try:
            container = self._docker.containers.get(self._container_name)
        except NotFound as e:
            raise RuntimeError(
                f"Sandbox container {self._container_name} not found"
            ) from e

        data_dir = shlex.quote(f"{cwd}/.opencode-data")
        safe_cwd = shlex.quote(cwd)
        cmd = [
            "/bin/sh",
            "-c",
            f"XDG_DATA_HOME={data_dir} exec opencode acp --cwd {safe_cwd}",
        ]

        logger.info(
            f"[ACP-DOCKER] Starting client: container={self._container_name} cwd={cwd}"
        )

        try:
            create = self._docker.api.exec_create(
                container.id,
                cmd=cmd,
                stdin=True,
                stdout=True,
                stderr=True,
                tty=False,
                workdir=cwd,
            )
            self._exec_id = create["Id"]

            sock = self._docker.api.exec_start(
                self._exec_id,
                detach=False,
                tty=False,
                stream=False,
                socket=True,
                demux=False,
            )
            self._socket = sock
            self._raw_sock = sock._sock if hasattr(sock, "_sock") else sock
            assert self._raw_sock is not None
            self._raw_sock.settimeout(0.1)

            self._stop_reader.clear()
            self._reader_thread = threading.Thread(
                target=self._read_responses, daemon=True
            )
            self._reader_thread.start()

            time.sleep(0.5)

            self._initialize(timeout=timeout)
            logger.info(
                f"[ACP-DOCKER] Client started: container={self._container_name}"
            )
        except Exception as e:
            logger.error(
                f"[ACP-DOCKER] Client start failed: container={self._container_name} error={e}"
            )
            self.stop()
            raise RuntimeError(f"Failed to start ACP exec client: {e}") from e

    def stop(self) -> None:
        session_ids = list(self._state.sessions.keys())
        logger.info(
            f"[ACP-DOCKER] Stopping client: container={self._container_name} sessions={session_ids}"
        )
        self._stop_reader.set()

        if self._raw_sock is not None:
            try:
                self._raw_sock.shutdown(socketlib.SHUT_RDWR)
            except Exception:
                pass
            try:
                self._raw_sock.close()
            except Exception:
                pass
        self._raw_sock = None
        self._socket = None
        self._exec_id = None

        if self._reader_thread is not None:
            self._reader_thread.join(timeout=2.0)
            self._reader_thread = None

        self._state = ACPClientState()

    # ------------------------------------------------------------------
    # JSON-RPC plumbing
    # ------------------------------------------------------------------
    def _read_responses(self) -> None:
        demux = _DemuxBuffer()
        text_buffer = ""
        packet_logger = get_packet_logger()

        while not self._stop_reader.is_set():
            sock = self._raw_sock
            if sock is None:
                break
            try:
                data = sock.recv(65536)
            except socketlib.timeout:
                continue
            except OSError as e:
                if not self._stop_reader.is_set():
                    logger.warning(
                        f"[ACP-DOCKER] Reader socket error: {e}, container={self._container_name}"
                    )
                break

            if not data:
                logger.warning(
                    f"[ACP-DOCKER] Reader EOF: container={self._container_name}"
                )
                break

            demux.feed(data)
            err = demux.drain_stderr()
            if err:
                logger.warning(
                    f"[ACP-DOCKER] stderr container={self._container_name}: "
                    f"{err.decode('utf-8', errors='replace').strip()[:500]}"
                )
            stdout = demux.drain_stdout()
            if stdout:
                text_buffer += stdout.decode("utf-8", errors="replace")
                while "\n" in text_buffer:
                    line, text_buffer = text_buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        message = json.loads(line)
                        packet_logger.log_jsonrpc_raw_message(
                            "IN", message, context="docker"
                        )
                        self._response_queue.put(message)
                    except json.JSONDecodeError:
                        logger.warning(
                            f"[ACP-DOCKER] Invalid JSON from agent: {line[:100]}"
                        )

    def _send_raw(self, payload: dict[str, Any]) -> None:
        if self._raw_sock is None:
            raise RuntimeError("Exec session not open")
        message = (json.dumps(payload) + "\n").encode("utf-8")
        with self._send_lock:
            view = memoryview(message)
            offset = 0
            while offset < len(view):
                sent = self._raw_sock.send(view[offset:])
                if sent == 0:
                    raise RuntimeError("Exec socket closed")
                offset += sent

    def _get_next_id(self) -> int:
        request_id = self._state.next_request_id
        self._state.next_request_id += 1
        return request_id

    def _send_request(self, method: str, params: dict[str, Any] | None = None) -> int:
        request_id = self._get_next_id()
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            payload["params"] = params

        get_packet_logger().log_jsonrpc_request(
            method, request_id, params, context="docker"
        )
        self._send_raw(payload)
        return request_id

    def _send_notification(
        self, method: str, params: dict[str, Any] | None = None
    ) -> None:
        if self._raw_sock is None:
            return
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        get_packet_logger().log_jsonrpc_request(method, None, params, context="docker")
        try:
            self._send_raw(payload)
        except Exception as e:
            logger.warning(f"[ACP-DOCKER] Failed to send notification: {e}")

    def _wait_for_response(
        self, request_id: int, timeout: float = 30.0
    ) -> dict[str, Any]:
        start = time.time()
        while True:
            remaining = timeout - (time.time() - start)
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
                # Not for us; put back for other consumers
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

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------
    def _create_session(self, cwd: str, timeout: float = 30.0) -> str:
        params = {"cwd": cwd, "mcpServers": []}
        request_id = self._send_request("session/new", params)
        result = self._wait_for_response(request_id, timeout)
        session_id = result.get("sessionId")
        if not session_id:
            raise RuntimeError("No session ID returned from session/new")
        self._state.sessions[session_id] = ACPSession(session_id=session_id, cwd=cwd)
        logger.info(f"[ACP-DOCKER] Created session: acp_session={session_id} cwd={cwd}")
        return session_id

    def _list_sessions(self, cwd: str, timeout: float = 10.0) -> list[dict[str, Any]]:
        try:
            request_id = self._send_request("session/list", {"cwd": cwd})
            result = self._wait_for_response(request_id, timeout)
            return result.get("sessions", [])
        except Exception as e:
            logger.info(f"[ACP-DOCKER] session/list unavailable: {e}")
            return []

    def _resume_session(self, session_id: str, cwd: str, timeout: float = 30.0) -> str:
        params = {"sessionId": session_id, "cwd": cwd, "mcpServers": []}
        request_id = self._send_request("session/resume", params)
        result = self._wait_for_response(request_id, timeout)
        resumed_id = result.get("sessionId", session_id)
        self._state.sessions[resumed_id] = ACPSession(session_id=resumed_id, cwd=cwd)
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
                f"[ACP-DOCKER] session/resume failed for {target_id}: {e}, falling back to session/new"
            )
            return None

    def resume_or_create_session(self, cwd: str, timeout: float = 30.0) -> str:
        if not self._state.initialized:
            raise RuntimeError("Client not initialized. Call start() first.")
        resumed = self._try_resume_existing_session(cwd, timeout)
        if resumed:
            return resumed
        return self._create_session(cwd=cwd, timeout=timeout)

    # ------------------------------------------------------------------
    # Prompt streaming
    # ------------------------------------------------------------------
    def send_message(
        self,
        message: str,
        session_id: str,
        timeout: float = ACP_MESSAGE_TIMEOUT,
    ) -> Generator[ACPEvent, None, None]:
        if session_id not in self._state.sessions:
            raise RuntimeError(
                f"Unknown session {session_id}. Known sessions: {list(self._state.sessions.keys())}"
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
                    f"[ACP-DOCKER] Prompt timeout: acp_session={session_id} events={events_yielded}, sending session/cancel"
                )
                try:
                    self.cancel(session_id=session_id)
                except Exception as cancel_err:
                    logger.warning(
                        f"[ACP-DOCKER] session/cancel failed on timeout: {cancel_err}"
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
                            f"[ACP-DOCKER] PromptResponse validation failed: {e}"
                        )

                elapsed_ms = (time.time() - start_time) * 1000
                logger.info(
                    f"[ACP-DOCKER] Prompt complete: reason={completion_reason} "
                    f"acp_session={session_id} events={events_yielded} elapsed={elapsed_ms:.0f}ms"
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
                    elapsed_ms = (time.time() - start_time) * 1000
                    logger.info(
                        f"[ACP-DOCKER] Prompt complete: reason={completion_reason} "
                        f"acp_session={session_id} events={events_yielded} elapsed={elapsed_ms:.0f}ms"
                    )
                    break

            elif "method" in message_data and "id" in message_data:
                self._send_error_response(
                    message_data["id"],
                    -32601,
                    f"Method not supported: {message_data['method']}",
                )

            else:
                logger.warning(
                    f"[ACP-DOCKER] Unhandled message: id={message_data.get('id')} "
                    f"method={message_data.get('method')} keys={list(message_data.keys())}"
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
                logger.warning(f"[ACP-DOCKER] Validation error for {update_type}: {e}")

    def _send_error_response(self, request_id: int, code: int, message: str) -> None:
        if self._raw_sock is None:
            return
        try:
            self._send_raw(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": code, "message": message},
                }
            )
        except Exception:
            pass

    def cancel(self, session_id: str | None = None) -> None:
        if session_id:
            if session_id in self._state.sessions:
                self._send_notification("session/cancel", {"sessionId": session_id})
        else:
            for sid in self._state.sessions:
                self._send_notification("session/cancel", {"sessionId": sid})

    def health_check(self, timeout: float = 5.0) -> bool:  # noqa: ARG002
        """Check if we can exec into the container.

        Lightweight: runs ``echo ok`` in the container and returns True if
        we got "ok" back. Does not require the ACP process to be running.
        """
        try:
            container = self._docker.containers.get(self._container_name)
        except NotFound:
            return False
        try:
            exit_code, output = container.exec_run(
                cmd=["echo", "ok"], stdout=True, stderr=False, tty=False
            )
            text = (
                output.decode("utf-8", errors="replace")
                if isinstance(output, bytes)
                else str(output)
            )
            return exit_code == 0 and "ok" in text
        except Exception:
            return False

    @property
    def is_running(self) -> bool:
        return self._raw_sock is not None and not self._stop_reader.is_set()

    def __enter__(self) -> "ACPExecClient":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()
