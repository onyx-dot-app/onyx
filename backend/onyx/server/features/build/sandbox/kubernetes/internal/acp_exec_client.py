"""ACP client that communicates via kubectl exec into the sandbox pod.

This client runs `opencode acp` directly in the sandbox pod via kubernetes exec,
using stdin/stdout for JSON-RPC communication. This bypasses the HTTP server
and uses the native ACP subprocess protocol.

Each message creates an ephemeral client (start → resume_or_create_session →
send_message → stop) to prevent concurrent processes from corrupting
opencode's flat file session storage.

Usage:
    client = ACPExecClient(
        pod_name="sandbox-abc123",
        namespace="onyx-sandboxes",
    )
    client.start(cwd="/workspace")
    session_id = client.resume_or_create_session(cwd="/workspace/sessions/abc")
    for event in client.send_message("What files are here?", session_id=session_id):
        print(event)
    client.stop()
"""

import json
import shlex
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
from kubernetes import client  # type: ignore
from kubernetes import config
from kubernetes.stream import stream as k8s_stream  # type: ignore
from kubernetes.stream.ws_client import WSClient  # type: ignore
from pydantic import BaseModel
from pydantic import ValidationError

from onyx.server.features.build.api.packet_logger import get_packet_logger
from onyx.server.features.build.configs import ACP_MESSAGE_TIMEOUT
from onyx.server.features.build.configs import SSE_KEEPALIVE_INTERVAL
from onyx.utils.logger import setup_logger

logger = setup_logger()

# ACP Protocol version
ACP_PROTOCOL_VERSION = 1

# Default client info
DEFAULT_CLIENT_INFO = {
    "name": "onyx-sandbox-k8s-exec",
    "title": "Onyx Sandbox Agent Client (K8s Exec)",
    "version": "1.0.0",
}


@dataclass
class SSEKeepalive:
    """Marker event to signal that an SSE keepalive should be sent.

    This is yielded when no ACP events have been received for SSE_KEEPALIVE_INTERVAL
    seconds, allowing the SSE stream to send a comment to keep the connection alive.

    Note: This is an internal event type - it's consumed by session/manager.py and
    converted to an SSE comment before leaving that layer. It should not be exposed
    to external consumers.
    """


# Union type for all possible events from send_message
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


class ACPExecClient:
    """ACP client that communicates via kubectl exec.

    Runs `opencode acp` in the sandbox pod and communicates via stdin/stdout
    through the kubernetes exec stream.
    """

    def __init__(
        self,
        pod_name: str,
        namespace: str,
        container: str = "sandbox",
        client_info: dict[str, Any] | None = None,
        client_capabilities: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the exec-based ACP client.

        Args:
            pod_name: Name of the sandbox pod
            namespace: Kubernetes namespace
            container: Container name within the pod
            client_info: Client identification info
            client_capabilities: Client capabilities to advertise
        """
        self._pod_name = pod_name
        self._namespace = namespace
        self._container = container
        self._client_info = client_info or DEFAULT_CLIENT_INFO
        self._client_capabilities = client_capabilities or {
            "fs": {"readTextFile": True, "writeTextFile": True},
            "terminal": True,
        }
        self._state = ACPClientState()
        self._ws_client: WSClient | None = None
        self._response_queue: Queue[dict[str, Any]] = Queue()
        self._reader_thread: threading.Thread | None = None
        self._stop_reader = threading.Event()
        self._k8s_client: client.CoreV1Api | None = None

    def _get_k8s_client(self) -> client.CoreV1Api:
        """Get or create kubernetes client."""
        if self._k8s_client is None:
            try:
                config.load_incluster_config()
            except config.ConfigException:
                config.load_kube_config()
            self._k8s_client = client.CoreV1Api()
        return self._k8s_client

    def start(self, cwd: str = "/workspace", timeout: float = 30.0) -> None:
        """Start the agent process via exec and initialize the ACP connection.

        Only performs the ACP `initialize` handshake. Sessions are created
        separately via `resume_or_create_session()`.

        Args:
            cwd: Working directory for the `opencode acp` process
            timeout: Timeout for initialization

        Raises:
            RuntimeError: If startup fails
        """
        if self._ws_client is not None:
            raise RuntimeError("Client already started. Call stop() first.")

        k8s = self._get_k8s_client()

        # Start opencode acp via exec.
        # Set XDG_DATA_HOME so opencode stores session data on the shared
        # workspace volume (accessible from file-sync container for snapshots)
        # instead of the container-local ~/.local/share/ filesystem.
        data_dir = shlex.quote(f"{cwd}/.opencode-data")
        safe_cwd = shlex.quote(cwd)
        exec_command = [
            "/bin/sh",
            "-c",
            f"XDG_DATA_HOME={data_dir} exec opencode acp --cwd {safe_cwd}",
        ]

        logger.info(f"[ACP] Starting client: pod={self._pod_name} cwd={cwd}")

        try:
            self._ws_client = k8s_stream(
                k8s.connect_get_namespaced_pod_exec,
                name=self._pod_name,
                namespace=self._namespace,
                container=self._container,
                command=exec_command,
                stdin=True,
                stdout=True,
                stderr=True,
                tty=False,
                _preload_content=False,
                _request_timeout=900,  # 15 minute timeout for long-running sessions
            )

            # Start reader thread
            self._stop_reader.clear()
            self._reader_thread = threading.Thread(
                target=self._read_responses, daemon=True
            )
            self._reader_thread.start()

            # Give process a moment to start
            time.sleep(0.5)

            # Initialize ACP connection (no session creation)
            self._initialize(timeout=timeout)

            logger.info(f"[ACP] Client started: pod={self._pod_name}")
        except Exception as e:
            logger.error(f"[ACP] Client start failed: pod={self._pod_name} error={e}")
            self.stop()
            raise RuntimeError(f"Failed to start ACP exec client: {e}") from e

    def _read_responses(self) -> None:
        """Background thread to read responses from the exec stream."""
        buffer = ""
        packet_logger = get_packet_logger()

        while not self._stop_reader.is_set():
            if self._ws_client is None:
                break

            try:
                if self._ws_client.is_open():
                    self._ws_client.update(timeout=0.1)

                    # Read stderr - log any agent errors
                    stderr_data = self._ws_client.read_stderr(timeout=0.01)
                    if stderr_data:
                        logger.warning(
                            f"[ACP] stderr pod={self._pod_name}: "
                            f"{stderr_data.strip()[:500]}"
                        )

                    # Read stdout
                    data = self._ws_client.read_stdout(timeout=0.1)
                    if data:
                        buffer += data

                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            line = line.strip()
                            if line:
                                try:
                                    message = json.loads(line)
                                    packet_logger.log_jsonrpc_raw_message(
                                        "IN", message, context="k8s"
                                    )
                                    self._response_queue.put(message)
                                except json.JSONDecodeError:
                                    logger.warning(
                                        f"[ACP] Invalid JSON from agent: "
                                        f"{line[:100]}"
                                    )

                else:
                    logger.warning(f"[ACP] WebSocket closed: pod={self._pod_name}")
                    break

            except Exception as e:
                if not self._stop_reader.is_set():
                    logger.warning(f"[ACP] Reader error: {e}, pod={self._pod_name}")
                break

    def stop(self) -> None:
        """Stop the exec session and clean up."""
        session_ids = list(self._state.sessions.keys())
        logger.info(
            f"[ACP] Stopping client: pod={self._pod_name} " f"sessions={session_ids}"
        )
        self._stop_reader.set()

        if self._ws_client is not None:
            try:
                self._ws_client.close()
            except Exception:
                pass
            self._ws_client = None

        if self._reader_thread is not None:
            self._reader_thread.join(timeout=2.0)
            self._reader_thread = None

        self._state = ACPClientState()

    def _get_next_id(self) -> int:
        """Get the next request ID."""
        request_id = self._state.next_request_id
        self._state.next_request_id += 1
        return request_id

    def _send_request(self, method: str, params: dict[str, Any] | None = None) -> int:
        """Send a JSON-RPC request."""
        if self._ws_client is None or not self._ws_client.is_open():
            raise RuntimeError("Exec session not open")

        request_id = self._get_next_id()
        request: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            request["params"] = params

        # Log the outgoing request
        packet_logger = get_packet_logger()
        packet_logger.log_jsonrpc_request(method, request_id, params, context="k8s")

        message = json.dumps(request) + "\n"
        self._ws_client.write_stdin(message)

        return request_id

    def _send_notification(
        self, method: str, params: dict[str, Any] | None = None
    ) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if self._ws_client is None or not self._ws_client.is_open():
            return

        notification: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            notification["params"] = params

        # Log the outgoing notification
        packet_logger = get_packet_logger()
        packet_logger.log_jsonrpc_request(method, None, params, context="k8s")

        message = json.dumps(notification) + "\n"
        self._ws_client.write_stdin(message)

    def _wait_for_response(
        self, request_id: int, timeout: float = 30.0
    ) -> dict[str, Any]:
        """Wait for a response to a specific request."""
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

                # Put back messages that aren't our response
                self._response_queue.put(message)

            except Empty:
                continue

    def _initialize(self, timeout: float = 30.0) -> dict[str, Any]:
        """Initialize the ACP connection."""
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
        """Create a new ACP session."""
        params = {
            "cwd": cwd,
            "mcpServers": [],
        }

        request_id = self._send_request("session/new", params)
        result = self._wait_for_response(request_id, timeout)

        session_id = result.get("sessionId")
        if not session_id:
            raise RuntimeError("No session ID returned from session/new")

        self._state.sessions[session_id] = ACPSession(session_id=session_id, cwd=cwd)
        logger.info(f"[ACP] Created session: acp_session={session_id} cwd={cwd}")

        return session_id

    def _list_sessions(self, cwd: str, timeout: float = 10.0) -> list[dict[str, Any]]:
        """List available ACP sessions, filtered by working directory.

        Returns:
            List of session info dicts with keys like 'sessionId', 'cwd', 'title'.
            Empty list if session/list is not supported or fails.
        """
        try:
            request_id = self._send_request("session/list", {"cwd": cwd})
            result = self._wait_for_response(request_id, timeout)
            sessions = result.get("sessions", [])
            logger.info(f"[ACP] session/list: {len(sessions)} sessions for cwd={cwd}")
            return sessions
        except Exception as e:
            logger.info(f"[ACP] session/list unavailable: {e}")
            return []

    def _resume_session(self, session_id: str, cwd: str, timeout: float = 30.0) -> str:
        """Resume an existing ACP session.

        Args:
            session_id: The ACP session ID to resume
            cwd: Working directory for the session
            timeout: Timeout for the resume request

        Returns:
            The session ID

        Raises:
            RuntimeError: If resume fails
        """
        params = {
            "sessionId": session_id,
            "cwd": cwd,
            "mcpServers": [],
        }

        request_id = self._send_request("session/resume", params)
        result = self._wait_for_response(request_id, timeout)

        # The response should contain the session ID
        resumed_id = result.get("sessionId", session_id)
        self._state.sessions[resumed_id] = ACPSession(session_id=resumed_id, cwd=cwd)

        logger.info(f"[ACP] Resumed session: acp_session={resumed_id} cwd={cwd}")
        return resumed_id

    def _try_resume_existing_session(self, cwd: str, timeout: float) -> str | None:
        """Try to find and resume an existing session for this workspace.

        When multiple API server replicas connect to the same sandbox pod,
        a previous replica may have already created an ACP session for this
        workspace. This method discovers and resumes that session so the
        agent retains conversation context.

        Args:
            cwd: Working directory to search for sessions
            timeout: Timeout for ACP requests

        Returns:
            The resumed session ID, or None if no session could be resumed
        """
        # List sessions for this workspace directory
        sessions = self._list_sessions(cwd, timeout=min(timeout, 10.0))
        if not sessions:
            return None

        # Pick the most recent session (first in list, assuming sorted)
        target = sessions[0]
        target_id = target.get("sessionId")
        if not target_id:
            logger.warning("[ACP] session/list returned session without sessionId")
            return None

        logger.info(
            f"[ACP] Resuming existing session: acp_session={target_id} "
            f"(found {len(sessions)})"
        )

        try:
            return self._resume_session(target_id, cwd, timeout)
        except Exception as e:
            logger.warning(
                f"[ACP] session/resume failed for {target_id}: {e}, "
                f"falling back to session/new"
            )
            return None

    def resume_or_create_session(self, cwd: str, timeout: float = 30.0) -> str:
        """Resume a session from opencode's on-disk storage, or create a new one.

        With ephemeral clients (one process per message), this always hits disk.
        Tries resume first to preserve conversation context, falls back to new.

        Args:
            cwd: Working directory for the session
            timeout: Timeout for ACP requests

        Returns:
            The ACP session ID
        """
        if not self._state.initialized:
            raise RuntimeError("Client not initialized. Call start() first.")

        # Try to resume from opencode's persisted storage
        resumed_id = self._try_resume_existing_session(cwd, timeout)
        if resumed_id:
            return resumed_id

        # Create a new session
        return self._create_session(cwd=cwd, timeout=timeout)

    def send_message(
        self,
        message: str,
        session_id: str,
        timeout: float = ACP_MESSAGE_TIMEOUT,
    ) -> Generator[ACPEvent, None, None]:
        """Send a message to a specific session and stream response events.

        Args:
            message: The message content to send
            session_id: The ACP session ID to send the message to
            timeout: Maximum time to wait for complete response (defaults to ACP_MESSAGE_TIMEOUT env var)

        Yields:
            Typed ACP schema event objects
        """
        if session_id not in self._state.sessions:
            raise RuntimeError(
                f"Unknown session {session_id}. "
                f"Known sessions: {list(self._state.sessions.keys())}"
            )
        packet_logger = get_packet_logger()

        logger.info(
            f"[ACP] Sending prompt: "
            f"acp_session={session_id} pod={self._pod_name} "
            f"queue_backlog={self._response_queue.qsize()}"
        )

        prompt_content = [{"type": "text", "text": message}]
        params = {
            "sessionId": session_id,
            "prompt": prompt_content,
        }

        request_id = self._send_request("session/prompt", params)
        start_time = time.time()
        last_event_time = time.time()
        events_yielded = 0
        keepalive_count = 0
        completion_reason = "unknown"

        while True:
            remaining = timeout - (time.time() - start_time)
            if remaining <= 0:
                completion_reason = "timeout"
                logger.warning(
                    f"[ACP] Prompt timeout: "
                    f"acp_session={session_id} events={events_yielded}, "
                    f"sending session/cancel"
                )
                try:
                    self.cancel(session_id=session_id)
                except Exception as cancel_err:
                    logger.warning(
                        f"[ACP] session/cancel failed on timeout: {cancel_err}"
                    )
                yield Error(code=-1, message="Timeout waiting for response")
                break

            try:
                message_data = self._response_queue.get(timeout=min(remaining, 1.0))
                last_event_time = time.time()
            except Empty:
                # Send SSE keepalive if idle
                idle_time = time.time() - last_event_time
                if idle_time >= SSE_KEEPALIVE_INTERVAL:
                    keepalive_count += 1
                    yield SSEKeepalive()
                    last_event_time = time.time()
                continue

            # Check for JSON-RPC response to our prompt request.
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
                    logger.warning(f"[ACP] Prompt error: {error_data}")
                    packet_logger.log_jsonrpc_response(
                        request_id, error=error_data, context="k8s"
                    )
                    yield Error(
                        code=error_data.get("code", -1),
                        message=error_data.get("message", "Unknown error"),
                    )
                else:
                    result = message_data.get("result", {})
                    packet_logger.log_jsonrpc_response(
                        request_id, result=result, context="k8s"
                    )
                    try:
                        prompt_response = PromptResponse.model_validate(result)
                        events_yielded += 1
                        yield prompt_response
                    except ValidationError as e:
                        logger.error(f"[ACP] PromptResponse validation failed: {e}")

                elapsed_ms = (time.time() - start_time) * 1000
                logger.info(
                    f"[ACP] Prompt complete: "
                    f"reason={completion_reason} acp_session={session_id} "
                    f"events={events_yielded} elapsed={elapsed_ms:.0f}ms"
                )
                break

            # Handle notifications (session/update)
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
                        f"[ACP] Prompt complete: "
                        f"reason={completion_reason} acp_session={session_id} "
                        f"events={events_yielded} elapsed={elapsed_ms:.0f}ms"
                    )
                    break

            # Handle requests from agent - send error response
            elif "method" in message_data and "id" in message_data:
                logger.debug(
                    f"[ACP] Unsupported agent request: "
                    f"method={message_data['method']}"
                )
                self._send_error_response(
                    message_data["id"],
                    -32601,
                    f"Method not supported: {message_data['method']}",
                )

            else:
                logger.warning(
                    f"[ACP] Unhandled message: "
                    f"id={message_data.get('id')} "
                    f"method={message_data.get('method')} "
                    f"keys={list(message_data.keys())}"
                )

    def _process_session_update(
        self, update: dict[str, Any]
    ) -> Generator[ACPEvent, None, None]:
        """Process a session/update notification and yield typed ACP schema objects."""
        update_type = update.get("sessionUpdate")
        if not isinstance(update_type, str):
            return

        # Map update types to their ACP schema classes.
        # Note: prompt_response is included because ACP sometimes sends it as a
        # notification WITHOUT a corresponding JSON-RPC response. We accept
        # either signal as turn completion (first one wins).
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
                logger.warning(f"[ACP] Validation error for {update_type}: {e}")
        elif update_type not in (
            "user_message_chunk",
            "available_commands_update",
            "session_info_update",
            "usage_update",
        ):
            logger.debug(f"[ACP] Unknown update type: {update_type}")

    def _send_error_response(self, request_id: int, code: int, message: str) -> None:
        """Send an error response to an agent request."""
        if self._ws_client is None or not self._ws_client.is_open():
            return

        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }

        self._ws_client.write_stdin(json.dumps(response) + "\n")

    def cancel(self, session_id: str | None = None) -> None:
        """Cancel the current operation on a session.

        Args:
            session_id: The ACP session ID to cancel. If None, cancels all sessions.
        """
        if session_id:
            if session_id in self._state.sessions:
                self._send_notification(
                    "session/cancel",
                    {"sessionId": session_id},
                )
        else:
            for sid in self._state.sessions:
                self._send_notification(
                    "session/cancel",
                    {"sessionId": sid},
                )

    def health_check(self, timeout: float = 5.0) -> bool:  # noqa: ARG002
        """Check if we can exec into the pod."""
        try:
            k8s = self._get_k8s_client()
            result = k8s_stream(
                k8s.connect_get_namespaced_pod_exec,
                name=self._pod_name,
                namespace=self._namespace,
                container=self._container,
                command=["echo", "ok"],
                stdin=False,
                stdout=True,
                stderr=False,
                tty=False,
            )
            return "ok" in result
        except Exception:
            return False

    @property
    def is_running(self) -> bool:
        """Check if the exec session is running."""
        return self._ws_client is not None and self._ws_client.is_open()

    def __enter__(self) -> "ACPExecClient":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit - ensures cleanup."""
        self.stop()
