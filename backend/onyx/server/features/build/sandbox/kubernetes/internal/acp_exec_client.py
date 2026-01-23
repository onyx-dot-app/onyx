"""ACP client that communicates via kubectl exec into the sandbox pod.

This client runs `opencode acp` directly in the sandbox pod via kubernetes exec,
using stdin/stdout for JSON-RPC communication. This bypasses the HTTP server
and uses the native ACP subprocess protocol.

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

            # Create session
            session_id = self._create_session(cwd=cwd, timeout=timeout)

            return session_id

        except Exception as e:
            self.stop()
            raise RuntimeError(f"Failed to start ACP exec client: {e}") from e

    def _read_responses(self) -> None:
        """Background thread to read responses from the exec stream."""
        buffer = ""

        while not self._stop_reader.is_set():
            if self._ws_client is None:
                break

            try:
                if self._ws_client.is_open():
                    # Read available data
                    self._ws_client.update(timeout=0.1)

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
                                    self._response_queue.put(message)
                                except json.JSONDecodeError:
                                    logger.warning(
                                        f"Invalid JSON from agent: {line[:100]}"
                                    )

                else:
                    break

            except Exception as e:
                if not self._stop_reader.is_set():
                    logger.debug(f"Reader error: {e}")
                break

    def stop(self) -> None:
        """Stop the exec session and clean up."""
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

    def send_message(
        self,
        message: str,
        timeout: float = 300.0,
    ) -> Generator[ACPEvent, None, None]:
        """Send a message and stream response events.

        Args:
            message: The message content to send
            timeout: Maximum time to wait for complete response

        Yields:
            Typed ACP schema event objects
        """
        if self._state.current_session is None:
            raise RuntimeError("No active session. Call start() first.")

        session_id = self._state.current_session.session_id

        prompt_content = [{"type": "text", "text": message}]
        params = {
            "sessionId": session_id,
            "prompt": prompt_content,
        }

        request_id = self._send_request("session/prompt", params)
        start_time = time.time()

        while True:
            remaining = timeout - (time.time() - start_time)
            if remaining <= 0:
                yield Error(code=-1, message="Timeout waiting for response")
                break

            try:
                message_data = self._response_queue.get(timeout=min(remaining, 1.0))
            except Empty:
                continue

            # Check for response to our prompt request
            if message_data.get("id") == request_id:
                if "error" in message_data:
                    error_data = message_data["error"]
                    yield Error(
                        code=error_data.get("code", -1),
                        message=error_data.get("message", "Unknown error"),
                    )
                else:
                    result = message_data.get("result", {})
                    try:
                        yield PromptResponse.model_validate(result)
                    except ValidationError:
                        pass
                break

            # Handle notifications (session/update)
            if message_data.get("method") == "session/update":
                params_data = message_data.get("params", {})
                update = params_data.get("update", {})

                for event in self._process_session_update(update):
                    yield event

            # Handle requests from agent - send error response
            elif "method" in message_data and "id" in message_data:
                self._send_error_response(
                    message_data["id"],
                    -32601,
                    f"Method not supported: {message_data['method']}",
                )

    def _process_session_update(
        self, update: dict[str, Any]
    ) -> Generator[ACPEvent, None, None]:
        """Process a session/update notification and yield typed ACP schema objects."""
        update_type = update.get("sessionUpdate")

        if update_type == "agent_message_chunk":
            try:
                yield AgentMessageChunk.model_validate(update)
            except ValidationError:
                pass

        elif update_type == "agent_thought_chunk":
            try:
                yield AgentThoughtChunk.model_validate(update)
            except ValidationError:
                pass

        elif update_type == "user_message_chunk":
            pass  # Echo of user message - skip

        elif update_type == "tool_call":
            try:
                yield ToolCallStart.model_validate(update)
            except ValidationError:
                pass

        elif update_type == "tool_call_update":
            try:
                yield ToolCallProgress.model_validate(update)
            except ValidationError:
                pass

        elif update_type == "plan":
            try:
                yield AgentPlanUpdate.model_validate(update)
            except ValidationError:
                pass

        elif update_type == "current_mode_update":
            try:
                yield CurrentModeUpdate.model_validate(update)
            except ValidationError:
                pass

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

    def health_check(self, timeout: float = 5.0) -> bool:
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
