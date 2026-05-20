"""Shared base for ACP exec clients across sandbox transports.

The Kubernetes and Docker sandbox backends both run ``opencode acp`` as a
subprocess in the sandbox container and shuttle JSON-RPC messages over a
transport-specific stream (a kubernetes exec WebSocket for K8s, a
multiplexed Docker exec socket for Docker). The JSON-RPC protocol, state
machine, session lifecycle, and event dispatch are identical between the
two — only the transport differs.

``ACPExecClientBase`` factors out the protocol layer. Subclasses provide
five hooks for transport open/close/poll/write/read; the base owns
everything else.
"""

from __future__ import annotations

import json
import threading
import time
from abc import ABC
from abc import abstractmethod
from collections.abc import Generator
from dataclasses import dataclass
from dataclasses import field
from queue import Empty
from queue import Queue
from typing import Any
from typing import cast
from typing import ClassVar

from acp.schema import AgentMessageChunk
from acp.schema import AgentPlanUpdate
from acp.schema import AgentThoughtChunk
from acp.schema import CurrentModeUpdate
from acp.schema import Error
from acp.schema import PromptResponse
from acp.schema import ToolCallProgress
from acp.schema import ToolCallStart
from pydantic import BaseModel
from pydantic import ValidationError

from onyx.server.features.build.api.packet_logger import get_packet_logger
from onyx.server.features.build.configs import ACP_MESSAGE_TIMEOUT
from onyx.server.features.build.configs import SSE_KEEPALIVE_INTERVAL
from onyx.server.features.build.sandbox.base import SSEKeepalive
from onyx.utils.logger import setup_logger

logger = setup_logger()


ACP_PROTOCOL_VERSION = 1


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
    """Represents an active ACP session."""

    session_id: str
    cwd: str


@dataclass
class ACPClientState:
    """Internal state for the ACP client."""

    initialized: bool = False
    sessions: dict[str, ACPSession] = field(default_factory=dict)
    next_request_id: int = 0
    agent_capabilities: dict[str, Any] = field(default_factory=dict)
    agent_info: dict[str, Any] = field(default_factory=dict)


class ACPExecClientBase(ABC):
    """Transport-agnostic ACP JSON-RPC client.

    Subclasses must define ``transport_name`` (``"k8s"`` / ``"docker"``)
    and implement the five abstract transport hooks below.
    """

    # ``transport_name`` drives the log prefix (``[K8S-ACP]`` / ``[DOCKER-ACP]``)
    # and the ``context=`` value the packet logger receives. Enforced via
    # ``__init_subclass__`` below since Python has no ``@abstractmethod``
    # equivalent for class variables.
    transport_name: ClassVar[str]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "transport_name" not in cls.__dict__ or not isinstance(
            cls.__dict__["transport_name"], str
        ):
            raise TypeError(
                f"{cls.__name__} must define a `transport_name: ClassVar[str]` "
                "class attribute (e.g. 'k8s', 'docker')."
            )

    def __init__(
        self,
        *,
        client_info: dict[str, Any],
        client_capabilities: dict[str, Any] | None = None,
    ) -> None:
        self._client_info = client_info
        self._client_capabilities = client_capabilities or {
            "fs": {"readTextFile": True, "writeTextFile": True},
            "terminal": True,
        }
        self._state = ACPClientState()
        self._response_queue: Queue[dict[str, Any]] = Queue()
        self._reader_thread: threading.Thread | None = None
        self._stop_reader = threading.Event()

    # ------------------------------------------------------------------
    # Transport hooks — subclass-specific
    # ------------------------------------------------------------------

    @abstractmethod
    def _open_transport(self, cwd: str) -> None:
        """Open the transport and spawn ``opencode acp --cwd <cwd>``."""

    @abstractmethod
    def _close_transport(self) -> None:
        """Close the transport. Must be idempotent and not raise."""

    @abstractmethod
    def _is_transport_open(self) -> bool:
        """Return True if the transport is still usable for I/O."""

    @abstractmethod
    def _write_line(self, line: str) -> None:
        """Write one newline-terminated JSON-RPC line to the transport."""

    @abstractmethod
    def _read_responses_loop(self) -> None:
        """Reader loop: parse incoming JSON lines and dispatch via
        :meth:`_enqueue_message`. Must respect ``self._stop_reader``."""

    @abstractmethod
    def _log_target(self) -> str:
        """Identifier for log lines (e.g. ``"pod=sandbox-abc"`` or
        ``"container=foo"``)."""

    # ------------------------------------------------------------------
    # Logging helpers
    # ------------------------------------------------------------------

    @property
    def _log_prefix(self) -> str:
        return f"[{self.transport_name.upper()}-ACP]"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, cwd: str = "/workspace", timeout: float = 30.0) -> None:
        """Open the transport, spawn the reader thread, and initialize ACP."""
        if self._is_transport_open():
            raise RuntimeError("Client already started. Call stop() first.")

        logger.info(
            "%s Starting client: %s cwd=%s", self._log_prefix, self._log_target(), cwd
        )

        try:
            self._open_transport(cwd)

            self._stop_reader.clear()
            self._reader_thread = threading.Thread(
                target=self._read_responses_loop, daemon=True
            )
            self._reader_thread.start()

            # Give opencode a moment to boot before sending initialize.
            time.sleep(0.5)

            self._initialize(timeout=timeout)

            logger.info("%s Client started: %s", self._log_prefix, self._log_target())
        except Exception as e:
            logger.error(
                "%s Client start failed: %s error=%s",
                self._log_prefix,
                self._log_target(),
                e,
            )
            self.stop()
            raise RuntimeError(
                f"Failed to start {self.transport_name} ACP exec client: {e}"
            ) from e

    def stop(self) -> None:
        """Tear down the reader thread and close the transport."""
        session_ids = list(self._state.sessions.keys())
        logger.info(
            "%s Stopping client: %s sessions=%s",
            self._log_prefix,
            self._log_target(),
            session_ids,
        )
        self._stop_reader.set()

        try:
            self._close_transport()
        except Exception:
            # ``_close_transport`` should swallow its own errors, but guard
            # so stop() never raises mid-cleanup.
            pass

        if self._reader_thread is not None:
            self._reader_thread.join(timeout=2.0)
            self._reader_thread = None

        self._state = ACPClientState()

    def _enqueue_message(self, message: dict[str, Any]) -> None:
        """Log and enqueue a parsed JSON-RPC message from the reader."""
        packet_logger = get_packet_logger()
        packet_logger.log_jsonrpc_raw_message(
            "IN", message, context=self.transport_name
        )
        self._response_queue.put(message)

    # ------------------------------------------------------------------
    # JSON-RPC primitives
    # ------------------------------------------------------------------

    def _get_next_id(self) -> int:
        request_id = self._state.next_request_id
        self._state.next_request_id += 1
        return request_id

    def _send_request(self, method: str, params: dict[str, Any] | None = None) -> int:
        if not self._is_transport_open():
            raise RuntimeError("Exec session not open")

        request_id = self._get_next_id()
        request: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            request["params"] = params

        packet_logger = get_packet_logger()
        packet_logger.log_jsonrpc_request(
            method, request_id, params, context=self.transport_name
        )

        self._write_line(json.dumps(request) + "\n")
        return request_id

    def _send_notification(
        self, method: str, params: dict[str, Any] | None = None
    ) -> None:
        if not self._is_transport_open():
            return

        notification: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            notification["params"] = params

        packet_logger = get_packet_logger()
        packet_logger.log_jsonrpc_request(
            method, None, params, context=self.transport_name
        )

        try:
            self._write_line(json.dumps(notification) + "\n")
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
                    return cast("dict[str, Any]", message.get("result", {}))

                # Not our response — put it back for the next consumer.
                self._response_queue.put(message)

            except Empty:
                continue

    # ------------------------------------------------------------------
    # ACP protocol
    # ------------------------------------------------------------------

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
            "%s Created session: acp_session=%s cwd=%s",
            self._log_prefix,
            session_id,
            cwd,
        )

        return session_id

    def _list_sessions(self, cwd: str, timeout: float = 10.0) -> list[dict[str, Any]]:
        try:
            request_id = self._send_request("session/list", {"cwd": cwd})
            result = self._wait_for_response(request_id, timeout)
            sessions = cast("list[dict[str, Any]]", result.get("sessions", []))
            logger.info(
                "%s session/list: %s sessions for cwd=%s",
                self._log_prefix,
                len(sessions),
                cwd,
            )
            return sessions
        except Exception as e:
            logger.info("%s session/list unavailable: %s", self._log_prefix, e)
            return []

    def _resume_session(self, session_id: str, cwd: str, timeout: float = 30.0) -> str:
        params = {"sessionId": session_id, "cwd": cwd, "mcpServers": []}

        request_id = self._send_request("session/resume", params)
        result = self._wait_for_response(request_id, timeout)

        resumed_id = result.get("sessionId", session_id)
        self._state.sessions[resumed_id] = ACPSession(session_id=resumed_id, cwd=cwd)

        logger.info(
            "%s Resumed session: acp_session=%s cwd=%s",
            self._log_prefix,
            resumed_id,
            cwd,
        )
        return resumed_id

    def _try_resume_existing_session(self, cwd: str, timeout: float) -> str | None:
        sessions = self._list_sessions(cwd, timeout=min(timeout, 10.0))
        if not sessions:
            return None

        target = sessions[0]
        target_id = target.get("sessionId")
        if not target_id:
            logger.warning(
                "%s session/list returned session without sessionId", self._log_prefix
            )
            return None

        logger.info(
            "%s Resuming existing session: acp_session=%s (found %s)",
            self._log_prefix,
            target_id,
            len(sessions),
        )

        try:
            return self._resume_session(target_id, cwd, timeout)
        except Exception as e:
            logger.warning(
                "%s session/resume failed for %s: %s, falling back to session/new",
                self._log_prefix,
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
                f"Known sessions: {list(self._state.sessions.keys())}"
            )
        packet_logger = get_packet_logger()

        logger.info(
            "%s Sending prompt: acp_session=%s %s queue_backlog=%s",
            self._log_prefix,
            session_id,
            self._log_target(),
            self._response_queue.qsize(),
        )

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
                    "%s Prompt timeout: acp_session=%s events=%s, sending session/cancel",
                    self._log_prefix,
                    session_id,
                    events_yielded,
                )
                try:
                    self.cancel(session_id=session_id)
                except Exception as cancel_err:
                    logger.warning(
                        "%s session/cancel failed on timeout: %s",
                        self._log_prefix,
                        cancel_err,
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
                    logger.warning("%s Prompt error: %s", self._log_prefix, error_data)
                    packet_logger.log_jsonrpc_response(
                        request_id, error=error_data, context=self.transport_name
                    )
                    yield Error(
                        code=error_data.get("code", -1),
                        message=error_data.get("message", "Unknown error"),
                    )
                else:
                    result = message_data.get("result", {})
                    packet_logger.log_jsonrpc_response(
                        request_id, result=result, context=self.transport_name
                    )
                    try:
                        prompt_response = PromptResponse.model_validate(result)
                        events_yielded += 1
                        yield prompt_response
                    except ValidationError as e:
                        logger.error(
                            "%s PromptResponse validation failed: %s",
                            self._log_prefix,
                            e,
                        )

                elapsed_ms = (time.time() - start_time) * 1000
                logger.info(
                    "%s Prompt complete: reason=%s acp_session=%s events=%s elapsed=%sms",
                    self._log_prefix,
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
                    elapsed_ms = (time.time() - start_time) * 1000
                    logger.info(
                        "%s Prompt complete: reason=%s acp_session=%s events=%s elapsed=%sms",
                        self._log_prefix,
                        completion_reason,
                        session_id,
                        events_yielded,
                        format(elapsed_ms, ".0f"),
                    )
                    break

            elif "method" in message_data and "id" in message_data:
                logger.debug(
                    "%s Unsupported agent request: method=%s",
                    self._log_prefix,
                    message_data["method"],
                )
                self._send_error_response(
                    message_data["id"],
                    -32601,
                    f"Method not supported: {message_data['method']}",
                )

            else:
                logger.warning(
                    "%s Unhandled message: id=%s method=%s keys=%s",
                    self._log_prefix,
                    message_data.get("id"),
                    message_data.get("method"),
                    list(message_data.keys()),
                )

    def _process_session_update(
        self, update: dict[str, Any]
    ) -> Generator[ACPEvent, None, None]:
        """Process a session/update notification and yield typed ACP events."""
        update_type = update.get("sessionUpdate")
        if not isinstance(update_type, str):
            return

        # ``prompt_response`` is included because some ACP versions emit it as
        # a notification *without* a corresponding JSON-RPC response — we
        # accept either signal as turn completion (first wins).
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
                    "%s Validation error for %s: %s",
                    self._log_prefix,
                    update_type,
                    e,
                )
        elif update_type not in (
            "user_message_chunk",
            "available_commands_update",
            "session_info_update",
            "usage_update",
        ):
            logger.debug("%s Unknown update type: %s", self._log_prefix, update_type)

    def _send_error_response(self, request_id: int, code: int, message: str) -> None:
        if not self._is_transport_open():
            return

        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }

        try:
            self._write_line(json.dumps(response) + "\n")
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
        return self._is_transport_open()

    def __enter__(self) -> "ACPExecClientBase":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()
