"""ACP client that communicates via kubectl exec into the sandbox pod.

This client runs `opencode acp` directly in the sandbox pod via kubernetes exec,
using stdin/stdout for JSON-RPC communication. This bypasses the HTTP server
and uses the native ACP subprocess protocol.

This module includes comprehensive logging for debugging ACP communication.
Enable logging by setting LOG_LEVEL=DEBUG or BUILD_PACKET_LOGGING=true.

Usage:
    client = ACPExecClient(
        pod_name="sandbox-abc123",
        namespace="onyx-sandboxes",
    )
    client.start(cwd="/workspace")
    for event in client.send_message("What files are here?"):
        print(event)
    client.stop()
"""

import json
import threading
import time
from collections.abc import Generator
from dataclasses import dataclass
from dataclasses import field
from queue import Empty
from queue import Queue
from typing import Any

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
    current_session: ACPSession | None = None
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
        self._prompt_count: int = 0  # Track how many prompts sent on this client

    def _get_k8s_client(self) -> client.CoreV1Api:
        """Get or create kubernetes client."""
        if self._k8s_client is None:
            try:
                config.load_incluster_config()
            except config.ConfigException:
                config.load_kube_config()
            self._k8s_client = client.CoreV1Api()
        return self._k8s_client

    def start(self, cwd: str = "/workspace", timeout: float = 30.0) -> str:
        """Start the agent process via exec and initialize a session.

        Args:
            cwd: Working directory for the agent
            timeout: Timeout for initialization

        Returns:
            The session ID

        Raises:
            RuntimeError: If startup fails
        """
        if self._ws_client is not None:
            raise RuntimeError("Client already started. Call stop() first.")

        k8s = self._get_k8s_client()

        # Start opencode acp via exec
        exec_command = ["opencode", "acp", "--cwd", cwd]

        logger.info(
            f"[ACP-LIFECYCLE] Starting ACP client: pod={self._pod_name}, "
            f"namespace={self._namespace}, cwd={cwd}"
        )

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

            # Initialize ACP connection
            self._initialize(timeout=timeout)

            # Try to resume an existing session first (handles multi-replica).
            # When multiple API server replicas connect to the same sandbox
            # pod, a previous replica may have already created a session for
            # this workspace.  Resuming preserves conversation context.
            session_id = self._try_resume_existing_session(cwd, timeout)
            resumed = session_id is not None

            if not session_id:
                # No existing session found — create a new one
                session_id = self._create_session(cwd=cwd, timeout=timeout)

            logger.info(
                f"[ACP-LIFECYCLE] ACP client started successfully: "
                f"pod={self._pod_name}, acp_session_id={session_id}, "
                f"cwd={cwd}, resumed={resumed}"
            )
            return session_id

        except Exception as e:
            logger.error(
                f"[ACP-LIFECYCLE] ACP client start FAILED: "
                f"pod={self._pod_name}, error={e}"
            )
            self.stop()
            raise RuntimeError(f"Failed to start ACP exec client: {e}") from e

    def _read_responses(self) -> None:
        """Background thread to read responses from the exec stream."""
        buffer = ""
        packet_logger = get_packet_logger()
        messages_read = 0

        logger.info(f"[ACP-READER] Reader thread started for pod={self._pod_name}")

        try:
            while not self._stop_reader.is_set():
                if self._ws_client is None:
                    logger.warning("[ACP-READER] WebSocket client is None, exiting")
                    break

                try:
                    if self._ws_client.is_open():
                        # Read available data
                        self._ws_client.update(timeout=0.1)

                        # Read stderr (channel 2) - log any agent errors
                        stderr_data = self._ws_client.read_stderr(timeout=0.01)
                        if stderr_data:
                            logger.warning(
                                f"[ACP-STDERR] pod={self._pod_name}: "
                                f"{stderr_data.strip()[:500]}"
                            )

                        # Read stdout (channel 1)
                        data = self._ws_client.read_stdout(timeout=0.1)
                        if data:
                            buffer += data

                            # Process complete lines
                            while "\n" in buffer:
                                line, buffer = buffer.split("\n", 1)
                                line = line.strip()
                                if line:
                                    try:
                                        message = json.loads(line)
                                        messages_read += 1
                                        # Log the raw incoming message
                                        packet_logger.log_jsonrpc_raw_message(
                                            "IN", message, context="k8s"
                                        )
                                        # Log key fields for every message
                                        msg_id = message.get("id")
                                        msg_method = message.get("method")
                                        update_type = None
                                        if msg_method == "session/update":
                                            update = message.get("params", {}).get(
                                                "update", {}
                                            )
                                            update_type = update.get("sessionUpdate")
                                        acp_sid = (
                                            self._state.current_session.session_id
                                            if self._state.current_session
                                            else "none"
                                        )
                                        logger.info(
                                            f"[ACP-READER] #{messages_read} "
                                            f"id={msg_id} method={msg_method} "
                                            f"update_type={update_type} "
                                            f"queue={self._response_queue.qsize()} "
                                            f"acp_session={acp_sid}"
                                        )
                                        self._response_queue.put(message)
                                    except json.JSONDecodeError:
                                        packet_logger.log_raw(
                                            "JSONRPC-PARSE-ERROR-K8S",
                                            {
                                                "raw_line": line[:500],
                                                "error": "JSON decode failed",
                                            },
                                        )
                                        logger.warning(
                                            f"Invalid JSON from agent: {line[:100]}"
                                        )

                    else:
                        logger.warning(
                            f"[ACP-READER] WebSocket closed: pod={self._pod_name}, "
                            f"total_messages_read={messages_read}"
                        )
                        packet_logger.log_raw(
                            "K8S-WEBSOCKET-CLOSED",
                            {"pod": self._pod_name, "namespace": self._namespace},
                        )
                        break

                except Exception as e:
                    if not self._stop_reader.is_set():
                        logger.warning(
                            f"[ACP-READER] Error: {e}, pod={self._pod_name}, "
                            f"total_messages_read={messages_read}"
                        )
                        packet_logger.log_raw(
                            "K8S-READER-ERROR",
                            {"error": str(e), "pod": self._pod_name},
                        )
                    break
        finally:
            # Flush any remaining data in buffer (e.g., PromptResponse without
            # trailing newline when the WebSocket closes)
            remaining = buffer.strip()
            if remaining:
                try:
                    message = json.loads(remaining)
                    packet_logger.log_jsonrpc_raw_message(
                        "IN", message, context="k8s-flush"
                    )
                    self._response_queue.put(message)
                    logger.info(
                        f"[ACP-READER] Flushed remaining buffer: "
                        f"id={message.get('id')} method={message.get('method')}"
                    )
                except json.JSONDecodeError:
                    packet_logger.log_raw(
                        "K8S-BUFFER-FLUSH-FAILED",
                        {"remaining": remaining[:500]},
                    )

            logger.info(
                f"[ACP-READER] Reader thread exiting: pod={self._pod_name}, "
                f"total_messages_read={messages_read}, "
                f"queue_size={self._response_queue.qsize()}"
            )

    def stop(self) -> None:
        """Stop the exec session and clean up."""
        acp_session = (
            self._state.current_session.session_id
            if self._state.current_session
            else "none"
        )
        logger.info(
            f"[ACP-LIFECYCLE] Stopping ACP client: pod={self._pod_name} "
            f"acp_session={acp_session} prompts_sent={self._prompt_count} "
            f"queue_size={self._response_queue.qsize()}"
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
        logger.info(
            f"[ACP-LIFECYCLE] ACP client stopped: pod={self._pod_name} "
            f"acp_session={acp_session}"
        )

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

        self._state.current_session = ACPSession(session_id=session_id, cwd=cwd)

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
            logger.info(
                f"[ACP-LIFECYCLE] session/list returned {len(sessions)} sessions "
                f"for cwd={cwd} pod={self._pod_name}"
            )
            return sessions
        except Exception as e:
            logger.info(
                f"[ACP-LIFECYCLE] session/list failed (may not be supported): "
                f"{e} pod={self._pod_name}"
            )
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
        self._state.current_session = ACPSession(session_id=resumed_id, cwd=cwd)

        logger.info(
            f"[ACP-LIFECYCLE] Resumed session: acp_session={resumed_id} "
            f"cwd={cwd} pod={self._pod_name}"
        )
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
        # Check if the agent supports session/list + session/resume
        session_caps = self._state.agent_capabilities.get("sessionCapabilities", {})
        supports_list = session_caps.get("list") is not None
        supports_resume = session_caps.get("resume") is not None

        if not supports_list:
            logger.info(
                "[ACP-LIFECYCLE] Agent does not support session/list, "
                "skipping session resume"
            )
            return None

        if not supports_resume:
            logger.info(
                "[ACP-LIFECYCLE] Agent does not support session/resume, "
                "skipping session resume"
            )
            return None

        # List sessions for this workspace directory
        sessions = self._list_sessions(cwd, timeout=min(timeout, 10.0))
        if not sessions:
            return None

        # Pick the most recent session (first in list, assuming sorted)
        target = sessions[0]
        target_id = target.get("sessionId")
        if not target_id:
            logger.warning(
                "[ACP-LIFECYCLE] session/list returned session without sessionId"
            )
            return None

        logger.info(
            f"[ACP-LIFECYCLE] Found {len(sessions)} existing session(s), "
            f"attempting resume of acp_session={target_id} "
            f"title={target.get('title')} pod={self._pod_name}"
        )

        try:
            return self._resume_session(target_id, cwd, timeout)
        except Exception as e:
            logger.warning(
                f"[ACP-LIFECYCLE] session/resume failed for "
                f"acp_session={target_id}: {e}, "
                f"falling back to session/new"
            )
            return None

    def send_message(
        self,
        message: str,
        timeout: float = ACP_MESSAGE_TIMEOUT,
    ) -> Generator[ACPEvent, None, None]:
        """Send a message and stream response events.

        Args:
            message: The message content to send
            timeout: Maximum time to wait for complete response (defaults to ACP_MESSAGE_TIMEOUT env var)

        Yields:
            Typed ACP schema event objects
        """
        if self._state.current_session is None:
            raise RuntimeError("No active session. Call start() first.")

        session_id = self._state.current_session.session_id
        packet_logger = get_packet_logger()
        self._prompt_count += 1
        prompt_num = self._prompt_count

        # Check WebSocket and reader thread health before sending
        ws_open = self._ws_client is not None and self._ws_client.is_open()
        reader_alive = (
            self._reader_thread is not None and self._reader_thread.is_alive()
        )
        queue_size_before = self._response_queue.qsize()

        logger.info(
            f"[ACP-SEND] === Prompt #{prompt_num} START === "
            f"acp_session={session_id} pod={self._pod_name} "
            f"ws_open={ws_open} reader_alive={reader_alive} "
            f"queue_size_before_drain={queue_size_before}"
        )

        # Drain any leftover messages from the queue before sending prompt.
        # These are messages that arrived between the previous prompt's
        # completion and this prompt's start (e.g., session_info_update,
        # available_commands_update).
        drained_count = 0
        while not self._response_queue.empty():
            try:
                stale_msg = self._response_queue.get_nowait()
                drained_count += 1
                stale_method = stale_msg.get("method")
                stale_id = stale_msg.get("id")
                stale_update_type = None
                if stale_method == "session/update":
                    stale_update = stale_msg.get("params", {}).get("update", {})
                    stale_update_type = stale_update.get("sessionUpdate")
                logger.info(
                    f"[ACP-SEND] Drained stale message #{drained_count}: "
                    f"id={stale_id} method={stale_method} "
                    f"update_type={stale_update_type}"
                )
            except Empty:
                break

        if drained_count > 0:
            logger.info(
                f"[ACP-SEND] Drained {drained_count} stale messages from queue "
                f"before prompt #{prompt_num}"
            )

        # Log the start of message processing
        packet_logger.log_raw(
            "ACP-SEND-MESSAGE-START-K8S",
            {
                "session_id": session_id,
                "pod": self._pod_name,
                "namespace": self._namespace,
                "prompt_num": prompt_num,
                "message_preview": (
                    message[:200] + "..." if len(message) > 200 else message
                ),
                "timeout": timeout,
                "queue_drained": drained_count,
                "ws_open": ws_open,
                "reader_alive": reader_alive,
            },
        )

        prompt_content = [{"type": "text", "text": message}]
        params = {
            "sessionId": session_id,
            "prompt": prompt_content,
        }

        request_id = self._send_request("session/prompt", params)
        logger.info(
            f"[ACP-SEND] Sent session/prompt: request_id={request_id} "
            f"acp_session={session_id} prompt_num={prompt_num}"
        )
        start_time = time.time()
        last_event_time = time.time()
        events_yielded = 0
        messages_processed = 0
        completion_reason = "unknown"

        while True:
            remaining = timeout - (time.time() - start_time)
            if remaining <= 0:
                completion_reason = "timeout"
                logger.warning(
                    f"[ACP-SEND] TIMEOUT: prompt #{prompt_num} "
                    f"acp_session={session_id} request_id={request_id} "
                    f"elapsed_ms={(time.time() - start_time) * 1000:.0f} "
                    f"events_yielded={events_yielded} "
                    f"messages_processed={messages_processed}"
                )
                packet_logger.log_raw(
                    "ACP-TIMEOUT-K8S",
                    {
                        "session_id": session_id,
                        "prompt_num": prompt_num,
                        "elapsed_ms": (time.time() - start_time) * 1000,
                        "events_yielded": events_yielded,
                        "messages_processed": messages_processed,
                    },
                )
                yield Error(code=-1, message="Timeout waiting for response")
                break

            try:
                message_data = self._response_queue.get(timeout=min(remaining, 1.0))
                last_event_time = time.time()
                messages_processed += 1

                # Log every dequeued message with comprehensive detail
                msg_id = message_data.get("id")
                msg_method = message_data.get("method")
                update_type = None
                if msg_method == "session/update":
                    update = message_data.get("params", {}).get("update", {})
                    update_type = update.get("sessionUpdate")
                logger.info(
                    f"[ACP-SEND] Dequeued #{messages_processed}: "
                    f"id={msg_id}({type(msg_id).__name__}) "
                    f"method={msg_method} update_type={update_type} "
                    f"request_id={request_id} id_match={msg_id == request_id} "
                    f"acp_session={session_id} prompt_num={prompt_num} "
                    f"queue_remaining={self._response_queue.qsize()}"
                )
            except Empty:
                # Check if reader thread is still alive
                if (
                    self._reader_thread is not None
                    and not self._reader_thread.is_alive()
                ):
                    completion_reason = "reader_thread_dead"
                    # Drain any final messages the reader flushed before dying
                    found_response = False
                    while not self._response_queue.empty():
                        try:
                            final_msg = self._response_queue.get_nowait()
                            logger.info(
                                f"[ACP-SEND] Final drain: id={final_msg.get('id')} "
                                f"method={final_msg.get('method')}"
                            )
                            if final_msg.get("id") == request_id:
                                found_response = True
                                if "error" in final_msg:
                                    error_data = final_msg["error"]
                                    yield Error(
                                        code=error_data.get("code", -1),
                                        message=error_data.get(
                                            "message", "Unknown error"
                                        ),
                                    )
                                else:
                                    result = final_msg.get("result", {})
                                    try:
                                        yield PromptResponse.model_validate(result)
                                    except ValidationError:
                                        pass
                                break
                        except Empty:
                            break

                    logger.warning(
                        f"[ACP-SEND] Reader thread DEAD: prompt #{prompt_num} "
                        f"acp_session={session_id} request_id={request_id} "
                        f"found_response={found_response} "
                        f"events_yielded={events_yielded} "
                        f"messages_processed={messages_processed}"
                    )
                    packet_logger.log_raw(
                        "ACP-CONNECTION-LOST-K8S",
                        {
                            "session_id": session_id,
                            "prompt_num": prompt_num,
                            "events_yielded": events_yielded,
                            "found_response_in_drain": found_response,
                        },
                    )
                    break

                # Check if we need to send an SSE keepalive
                idle_time = time.time() - last_event_time
                if idle_time >= SSE_KEEPALIVE_INTERVAL:
                    logger.info(
                        f"[ACP-SEND] SSE keepalive: prompt #{prompt_num} "
                        f"acp_session={session_id} idle={idle_time:.1f}s "
                        f"elapsed={(time.time() - start_time):.1f}s "
                        f"events_yielded={events_yielded} "
                        f"messages_processed={messages_processed} "
                        f"ws_open={self._ws_client is not None and self._ws_client.is_open()} "
                        f"reader_alive={self._reader_thread is not None and self._reader_thread.is_alive()}"
                    )
                    packet_logger.log_raw(
                        "SSE-KEEPALIVE-YIELD",
                        {
                            "session_id": session_id,
                            "prompt_num": prompt_num,
                            "idle_seconds": idle_time,
                        },
                    )
                    yield SSEKeepalive()
                    last_event_time = time.time()
                continue

            # Check for JSON-RPC response to our prompt request.
            msg_id = message_data.get("id")
            is_response = "method" not in message_data and (
                msg_id == request_id
                or (msg_id is not None and str(msg_id) == str(request_id))
            )
            if is_response and msg_id != request_id:
                logger.warning(
                    f"[ACP-SEND] ID type mismatch: "
                    f"got {type(msg_id).__name__}({msg_id}), "
                    f"expected {type(request_id).__name__}({request_id})"
                )
            if is_response:
                completion_reason = "jsonrpc_response"
                if "error" in message_data:
                    error_data = message_data["error"]
                    completion_reason = "jsonrpc_error"
                    logger.warning(
                        f"[ACP-SEND] JSON-RPC ERROR response: prompt #{prompt_num} "
                        f"acp_session={session_id} request_id={request_id} "
                        f"error={error_data}"
                    )
                    packet_logger.log_jsonrpc_response(
                        request_id, error=error_data, context="k8s"
                    )
                    yield Error(
                        code=error_data.get("code", -1),
                        message=error_data.get("message", "Unknown error"),
                    )
                else:
                    result = message_data.get("result", {})
                    logger.info(
                        f"[ACP-SEND] PromptResponse via JSON-RPC: "
                        f"prompt #{prompt_num} acp_session={session_id} "
                        f"request_id={request_id} "
                        f"stop_reason={result.get('stopReason')} "
                        f"result_keys={list(result.keys())}"
                    )
                    packet_logger.log_jsonrpc_response(
                        request_id, result=result, context="k8s"
                    )
                    try:
                        prompt_response = PromptResponse.model_validate(result)
                        packet_logger.log_acp_event_yielded(
                            "prompt_response", prompt_response
                        )
                        events_yielded += 1
                        yield prompt_response
                    except ValidationError as e:
                        logger.error(
                            f"[ACP-SEND] PromptResponse VALIDATION FAILED: "
                            f"prompt #{prompt_num} error={e} result={result}"
                        )
                        packet_logger.log_raw(
                            "ACP-VALIDATION-ERROR-K8S",
                            {"type": "prompt_response", "error": str(e)},
                        )

                # Log completion
                elapsed_ms = (time.time() - start_time) * 1000
                logger.info(
                    f"[ACP-SEND] === Prompt #{prompt_num} COMPLETE === "
                    f"reason={completion_reason} acp_session={session_id} "
                    f"request_id={request_id} events={events_yielded} "
                    f"messages={messages_processed} elapsed={elapsed_ms:.0f}ms"
                )
                packet_logger.log_raw(
                    "ACP-SEND-MESSAGE-COMPLETE-K8S",
                    {
                        "session_id": session_id,
                        "prompt_num": prompt_num,
                        "events_yielded": events_yielded,
                        "messages_processed": messages_processed,
                        "elapsed_ms": elapsed_ms,
                        "completion_reason": completion_reason,
                    },
                )
                break

            # Handle notifications (session/update)
            if message_data.get("method") == "session/update":
                params_data = message_data.get("params", {})
                update = params_data.get("update", {})
                update_type_val = update.get("sessionUpdate")

                packet_logger.log_jsonrpc_notification(
                    "session/update",
                    {"update_type": update_type_val, "prompt_num": prompt_num},
                    context="k8s",
                )

                prompt_complete = False
                for event in self._process_session_update(update):
                    events_yielded += 1
                    event_type = self._get_event_type_name(event)
                    packet_logger.log_acp_event_yielded(event_type, event)
                    yield event
                    if isinstance(event, PromptResponse):
                        prompt_complete = True
                        break

                if prompt_complete:
                    completion_reason = "prompt_response_via_notification"
                    elapsed_ms = (time.time() - start_time) * 1000
                    logger.info(
                        f"[ACP-SEND] === Prompt #{prompt_num} COMPLETE === "
                        f"reason={completion_reason} acp_session={session_id} "
                        f"request_id={request_id} events={events_yielded} "
                        f"messages={messages_processed} elapsed={elapsed_ms:.0f}ms"
                    )
                    packet_logger.log_raw(
                        "ACP-SEND-MESSAGE-COMPLETE-K8S",
                        {
                            "session_id": session_id,
                            "prompt_num": prompt_num,
                            "events_yielded": events_yielded,
                            "messages_processed": messages_processed,
                            "elapsed_ms": elapsed_ms,
                            "completion_reason": completion_reason,
                        },
                    )
                    break

            # Handle requests from agent - send error response
            elif "method" in message_data and "id" in message_data:
                logger.info(
                    f"[ACP-SEND] Agent request (unsupported): "
                    f"method={message_data['method']} id={message_data['id']} "
                    f"prompt_num={prompt_num} acp_session={session_id}"
                )
                packet_logger.log_raw(
                    "ACP-UNSUPPORTED-REQUEST-K8S",
                    {
                        "method": message_data["method"],
                        "id": message_data["id"],
                        "prompt_num": prompt_num,
                    },
                )
                self._send_error_response(
                    message_data["id"],
                    -32601,
                    f"Method not supported: {message_data['method']}",
                )

            else:
                # Message didn't match any handler
                logger.warning(
                    f"[ACP-SEND] UNHANDLED message: "
                    f"id={message_data.get('id')} "
                    f"method={message_data.get('method')} "
                    f"keys={list(message_data.keys())} "
                    f"request_id={request_id} prompt_num={prompt_num} "
                    f"acp_session={session_id} "
                    f"raw_preview={json.dumps(message_data)[:300]}"
                )

    def _get_event_type_name(self, event: ACPEvent) -> str:
        """Get the type name for an ACP event."""
        if isinstance(event, AgentMessageChunk):
            return "agent_message_chunk"
        elif isinstance(event, AgentThoughtChunk):
            return "agent_thought_chunk"
        elif isinstance(event, ToolCallStart):
            return "tool_call_start"
        elif isinstance(event, ToolCallProgress):
            return "tool_call_progress"
        elif isinstance(event, AgentPlanUpdate):
            return "agent_plan_update"
        elif isinstance(event, CurrentModeUpdate):
            return "current_mode_update"
        elif isinstance(event, PromptResponse):
            return "prompt_response"
        elif isinstance(event, Error):
            return "error"
        elif isinstance(event, SSEKeepalive):
            return "sse_keepalive"
        return "unknown"

    def _process_session_update(
        self, update: dict[str, Any]
    ) -> Generator[ACPEvent, None, None]:
        """Process a session/update notification and yield typed ACP schema objects."""
        update_type = update.get("sessionUpdate")
        packet_logger = get_packet_logger()

        if update_type == "agent_message_chunk":
            try:
                yield AgentMessageChunk.model_validate(update)
            except ValidationError as e:
                packet_logger.log_raw(
                    "ACP-VALIDATION-ERROR-K8S",
                    {"update_type": update_type, "error": str(e), "update": update},
                )

        elif update_type == "agent_thought_chunk":
            try:
                yield AgentThoughtChunk.model_validate(update)
            except ValidationError as e:
                packet_logger.log_raw(
                    "ACP-VALIDATION-ERROR-K8S",
                    {"update_type": update_type, "error": str(e), "update": update},
                )

        elif update_type == "user_message_chunk":
            # Echo of user message - skip but log
            packet_logger.log_raw(
                "ACP-SKIPPED-UPDATE-K8S", {"type": "user_message_chunk"}
            )

        elif update_type == "tool_call":
            try:
                yield ToolCallStart.model_validate(update)
            except ValidationError as e:
                packet_logger.log_raw(
                    "ACP-VALIDATION-ERROR-K8S",
                    {"update_type": update_type, "error": str(e), "update": update},
                )

        elif update_type == "tool_call_update":
            try:
                yield ToolCallProgress.model_validate(update)
            except ValidationError as e:
                packet_logger.log_raw(
                    "ACP-VALIDATION-ERROR-K8S",
                    {"update_type": update_type, "error": str(e), "update": update},
                )

        elif update_type == "plan":
            try:
                yield AgentPlanUpdate.model_validate(update)
            except ValidationError as e:
                packet_logger.log_raw(
                    "ACP-VALIDATION-ERROR-K8S",
                    {"update_type": update_type, "error": str(e), "update": update},
                )

        elif update_type == "current_mode_update":
            try:
                yield CurrentModeUpdate.model_validate(update)
            except ValidationError as e:
                packet_logger.log_raw(
                    "ACP-VALIDATION-ERROR-K8S",
                    {"update_type": update_type, "error": str(e), "update": update},
                )

        elif update_type == "prompt_response":
            # Some ACP versions send PromptResponse as a session/update notification
            # rather than (or in addition to) a JSON-RPC response.
            logger.info(
                "[ACP] Received prompt_response via session/update notification"
            )
            try:
                yield PromptResponse.model_validate(update)
            except ValidationError as e:
                packet_logger.log_raw(
                    "ACP-VALIDATION-ERROR-K8S",
                    {"update_type": update_type, "error": str(e), "update": update},
                )

        elif update_type == "available_commands_update":
            # Skip command updates
            packet_logger.log_raw(
                "ACP-SKIPPED-UPDATE-K8S", {"type": "available_commands_update"}
            )

        elif update_type == "session_info_update":
            # Skip session info updates
            packet_logger.log_raw(
                "ACP-SKIPPED-UPDATE-K8S", {"type": "session_info_update"}
            )

        else:
            # Unknown update types are logged
            packet_logger.log_raw(
                "ACP-UNKNOWN-UPDATE-TYPE-K8S",
                {"update_type": update_type, "update": update},
            )

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

    def cancel(self) -> None:
        """Cancel the current operation."""
        if self._state.current_session is None:
            return

        self._send_notification(
            "session/cancel",
            {"sessionId": self._state.current_session.session_id},
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

    @property
    def session_id(self) -> str | None:
        """Get the current session ID, if any."""
        if self._state.current_session:
            return self._state.current_session.session_id
        return None

    def __enter__(self) -> "ACPExecClient":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit - ensures cleanup."""
        self.stop()
