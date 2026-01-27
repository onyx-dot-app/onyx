"""Communication with CLI agent subprocess using ACP (Agent Client Protocol).

ACP is a JSON-RPC 2.0 based protocol for communicating with coding agents.
See: https://agentclientprotocol.com

Usage:
    # Simple usage with context manager
    with ACPAgentClient(cwd="/path/to/project") as client:
        for packet in client.send_message("What files are here?"):
            print(packet)

    # Manual lifecycle management
    client = ACPAgentClient()
    client.start(cwd="/path/to/project")
    for packet in client.send_message("Hello"):
        print(packet)
    client.stop()
"""

import json
import os
import select
import shutil
import subprocess
import threading
from collections.abc import Generator
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

from acp.schema import AgentMessageChunk
from acp.schema import AgentPlanUpdate
from acp.schema import AgentThoughtChunk
from acp.schema import CurrentModeUpdate
from acp.schema import Error
from acp.schema import PromptResponse
from acp.schema import ToolCallProgress
from acp.schema import ToolCallStart
from pydantic import ValidationError


# ACP Protocol version
ACP_PROTOCOL_VERSION = 1

# Default client info
DEFAULT_CLIENT_INFO = {
    "name": "onyx-sandbox",
    "title": "Onyx Sandbox Agent Client",
    "version": "1.0.0",
}

SESSION_CREATION_TIMEOUT = 30.0  # 30 seconds
TIMEOUT = 900.0  # 15 minutes
SINGLE_READ_TIMEOUT = 10.0  # 10 seconds


# =============================================================================
# Response Event Types (from acp.schema + custom completion/error types)
# =============================================================================

# Union type for all possible events from send_message
# Uses ACP schema types for session updates, plus our completion type
ACPEvent = (
    AgentMessageChunk  # Text/image content from agent
    | AgentThoughtChunk  # Agent's internal reasoning
    | ToolCallStart  # Tool invocation started
    | ToolCallProgress  # Tool execution progress/result
    | AgentPlanUpdate  # Agent's execution plan
    | CurrentModeUpdate  # Agent mode change
    | PromptResponse  # Agent finished (contains stop_reason)
    | Error  # An error occurred
)


# =============================================================================
# Internal State Types
# =============================================================================


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


def _find_opencode_binary() -> str | None:
    """Find the opencode binary path.

    Returns:
        Path to opencode binary, or None if not found
    """
    # Check PATH first
    opencode_path = shutil.which("opencode")
    if opencode_path:
        return opencode_path

    # Try common installation paths
    common_paths = [
        Path.home() / ".opencode" / "bin" / "opencode",
        Path("/usr/local/bin/opencode"),
    ]
    for path in common_paths:
        if path.exists():
            return str(path)

    return None


class ACPAgentClient:
    """ACP (Agent Client Protocol) client for communication with CLI agents.

    Implements JSON-RPC 2.0 over stdin/stdout as specified by ACP.
    Manages the agent subprocess lifecycle internally.

    Usage:
        # With context manager (recommended)
        with ACPAgentClient(cwd="/path/to/project") as client:
            for packet in client.send_message("Hello"):
                print(packet)

        # Manual lifecycle
        client = ACPAgentClient()
        client.start(cwd="/path/to/project")
        try:
            for packet in client.send_message("Hello"):
                print(packet)
        finally:
            client.stop()
    """

    def __init__(
        self,
        cwd: str | None = None,
        opencode_path: str | None = None,
        client_info: dict[str, Any] | None = None,
        client_capabilities: dict[str, Any] | None = None,
        auto_start: bool = True,
    ) -> None:
        """Initialize the ACP client.

        Args:
            cwd: Working directory for the agent. If provided and auto_start=True,
                 the agent will be started immediately.
            opencode_path: Path to opencode binary. Auto-detected if not provided.
            client_info: Client identification info (name, title, version)
            client_capabilities: Client capabilities to advertise
            auto_start: If True and cwd is provided, start the agent immediately
        """
        self._opencode_path = opencode_path or _find_opencode_binary()
        self._client_info = client_info or DEFAULT_CLIENT_INFO
        self._client_capabilities = client_capabilities or {
            "fs": {
                "readTextFile": True,
                "writeTextFile": True,
            },
            "terminal": True,
        }
        self._state = ACPClientState()
        self._process: subprocess.Popen[str] | None = None
        self._read_lock = threading.Lock()
        self._cwd: str | None = None

        # Auto-start if cwd provided
        if cwd and auto_start:
            self.start(cwd=cwd)

    def __enter__(self) -> "ACPAgentClient":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit - ensures cleanup."""
        self.stop()

    def start(
        self,
        cwd: str | None = None,
        mcp_servers: list[dict[str, Any]] | None = None,
        timeout: float = 30.0,
    ) -> str:
        """Start the agent process and initialize a session.

        This method:
        1. Starts the opencode acp subprocess
        2. Sends the initialize handshake
        3. Creates a new session

        Args:
            cwd: Working directory for the agent (defaults to current directory)
            mcp_servers: Optional MCP server configurations
            timeout: Timeout for initialization and session creation

        Returns:
            The session ID

        Raises:
            RuntimeError: If opencode is not found or startup fails
        """
        if self._process is not None:
            raise RuntimeError("Agent already started. Call stop() first.")

        if not self._opencode_path:
            raise RuntimeError(
                "opencode binary not found. Install opencode or provide opencode_path."
            )

        self._cwd = cwd or os.getcwd()

        # Start the opencode acp process
        self._process = subprocess.Popen(
            [self._opencode_path, "acp", "--cwd", self._cwd],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        try:
            # Initialize the ACP connection
            self._initialize(timeout=timeout)

            # Create a session
            session_id = self._create_session(
                cwd=self._cwd,
                mcp_servers=mcp_servers,
                timeout=timeout,
            )

            return session_id

        except Exception:
            # Clean up on failure
            self.stop()
            raise

    def stop(self) -> None:
        """Stop the agent process and clean up resources."""
        if self._process is not None:
            if self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._process.kill()

            self._process = None

        # Reset state
        self._state = ACPClientState()

    def _get_next_id(self) -> int:
        """Get the next request ID."""
        request_id = self._state.next_request_id
        self._state.next_request_id += 1
        return request_id

    def _ensure_running(self) -> subprocess.Popen[str]:
        """Ensure the process is running and return it.

        Raises:
            RuntimeError: If process is not running
        """
        if self._process is None:
            raise RuntimeError("Agent not started. Call start() first.")

        if self._process.poll() is not None:
            raise RuntimeError(
                f"Agent process has terminated with code {self._process.returncode}"
            )

        return self._process

    def _send_request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> int:
        """Send a JSON-RPC request to the agent.

        Args:
            method: The RPC method name
            params: Optional parameters for the method

        Returns:
            The request ID

        Raises:
            RuntimeError: If the process has terminated or pipe is broken
        """
        process = self._ensure_running()

        if process.stdin is None:
            raise RuntimeError("Process stdin is not available")

        request_id = self._get_next_id()
        request: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            request["params"] = params

        try:
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
        except BrokenPipeError:
            raise RuntimeError("Agent process stdin pipe is broken")

        return request_id

    def _send_notification(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> None:
        """Send a JSON-RPC notification (no response expected).

        Args:
            method: The notification method name
            params: Optional parameters

        Raises:
            RuntimeError: If the process has terminated or pipe is broken
        """
        process = self._ensure_running()

        if process.stdin is None:
            raise RuntimeError("Process stdin is not available")

        notification: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            notification["params"] = params

        try:
            process.stdin.write(json.dumps(notification) + "\n")
            process.stdin.flush()
        except BrokenPipeError:
            raise RuntimeError("Agent process stdin pipe is broken")

    def _read_message(
        self,
        timeout: float | None = None,
    ) -> dict[str, Any] | None:
        """Read a single JSON-RPC message from the agent.

        Args:
            timeout: Optional timeout in seconds

        Returns:
            The parsed JSON message, or None if timeout/EOF

        Raises:
            RuntimeError: If process stdout is not available
        """
        process = self._ensure_running()

        if process.stdout is None:
            raise RuntimeError("Process stdout is not available")

        with self._read_lock:
            if timeout is not None:
                stdout_fd = process.stdout.fileno()
                readable, _, _ = select.select([stdout_fd], [], [], timeout)
                if not readable:
                    return None

            line = process.stdout.readline()
            if not line:
                return None

            line = line.strip()
            if not line:
                return None

            try:
                return json.loads(line)
            except json.JSONDecodeError:
                return {
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32700,
                        "message": f"Parse error: {line[:100]}",
                    },
                }

    def _wait_for_response(
        self,
        request_id: int,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Wait for a response to a specific request.

        Args:
            request_id: The request ID to wait for
            timeout: Maximum time to wait

        Returns:
            The response result

        Raises:
            RuntimeError: If timeout, error response, or process dies
        """
        import time

        start_time = time.time()

        while True:
            remaining = timeout - (time.time() - start_time)
            if remaining <= 0:
                raise RuntimeError(
                    f"Timeout waiting for response to request {request_id}"
                )

            message = self._read_message(timeout=min(remaining, 1.0))

            if message is None:
                process = self._ensure_running()
                if process.poll() is not None:
                    raise RuntimeError(
                        f"Agent process terminated with code {process.returncode}"
                    )
                continue

            # Check if this is the response we're waiting for
            if message.get("id") == request_id:
                if "error" in message:
                    error = message["error"]
                    raise RuntimeError(
                        f"ACP error {error.get('code')}: {error.get('message')}"
                    )
                return message.get("result", {})

    def _initialize(self, timeout: float = SESSION_CREATION_TIMEOUT) -> dict[str, Any]:
        """Initialize the ACP connection (internal).

        Args:
            timeout: Maximum time to wait for response

        Returns:
            The agent's capabilities and info
        """
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

    def _create_session(
        self,
        cwd: str,
        mcp_servers: list[dict[str, Any]] | None = None,
        timeout: float = SESSION_CREATION_TIMEOUT,
    ) -> str:
        """Create a new ACP session (internal).

        Args:
            cwd: Working directory for the session
            mcp_servers: Optional MCP server configurations
            timeout: Maximum time to wait for response

        Returns:
            The session ID
        """
        # Note: opencode requires cwd and mcpServers
        params: dict[str, Any] = {
            "cwd": cwd,
            "mcpServers": mcp_servers or [],
        }

        request_id = self._send_request("session/new", params)
        result = self._wait_for_response(request_id, timeout)

        session_id = result.get("sessionId")
        if not session_id:
            raise RuntimeError("No session ID returned from session/new")

        self._state.current_session = ACPSession(
            session_id=session_id,
            cwd=cwd,
        )

        return session_id

    def send_message(
        self,
        message: str,
        timeout: float = TIMEOUT,
    ) -> Generator[ACPEvent, None, None]:
        """Send a message and stream response events.

        Args:
            message: The message content to send
            timeout: Maximum time to wait for complete response

        Yields:
            Typed ACP schema event objects (ACPEvent union):
            - AgentMessageChunk: Text/image content from the agent
            - AgentThoughtChunk: Agent's internal reasoning
            - ToolCallStart: Tool invocation started
            - ToolCallProgress: Tool execution progress/result
            - AgentPlanUpdate: Agent's execution plan
            - CurrentModeUpdate: Agent mode change
            - PromptResponse: Agent finished (has stop_reason)
            - Error: An error occurred

        Raises:
            RuntimeError: If no session or prompt fails
        """
        import time

        if self._state.current_session is None:
            raise RuntimeError("No active session. Call start() first.")

        session_id = self._state.current_session.session_id
        process = self._ensure_running()

        # Build prompt content blocks
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

            message_data = self._read_message(
                timeout=min(remaining, SINGLE_READ_TIMEOUT)
            )

            if message_data is None:
                if process.poll() is not None:
                    yield Error(
                        code=-1,
                        message=f"Agent process terminated with code {process.returncode}",
                    )
                    break
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
                    yield PromptResponse.model_validate(result)
                break

            # Handle notifications (session/update)
            if message_data.get("method") == "session/update":
                params_data = message_data.get("params", {})
                update = params_data.get("update", {})

                for event in self._process_session_update(update):
                    yield event

            # Handle requests from agent (e.g., fs/readTextFile)
            elif "method" in message_data and "id" in message_data:
                self._send_error_response(
                    message_data["id"],
                    -32601,
                    f"Method not supported: {message_data['method']}",
                )

    def _process_session_update(
        self, update: dict[str, Any]
    ) -> Generator[ACPEvent, None, None]:
        """Process a session/update notification and yield typed ACP schema objects.

        Validates and returns the actual ACP schema types directly.
        Invalid updates are silently skipped.
        """
        update_type = update.get("sessionUpdate")

        if update_type == "agent_message_chunk":
            try:
                yield AgentMessageChunk.model_validate(update)
            except ValidationError:
                pass  # Skip invalid updates

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

        elif update_type == "available_commands_update":
            # Skip command updates - not relevant for consumers
            pass

        elif update_type == "current_mode_update":
            try:
                yield CurrentModeUpdate.model_validate(update)
            except ValidationError:
                pass

        elif update_type == "session_info_update":
            # Skip session info updates - internal bookkeeping
            pass

        # Unknown update types are silently skipped

    def _send_error_response(
        self,
        request_id: int,
        code: int,
        message: str,
    ) -> None:
        """Send an error response to an agent request."""
        process = self._process
        if process is None or process.stdin is None:
            return

        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": code,
                "message": message,
            },
        }

        try:
            process.stdin.write(json.dumps(response) + "\n")
            process.stdin.flush()
        except BrokenPipeError:
            pass

    def cancel(self) -> None:
        """Cancel the current operation."""
        if self._state.current_session is None:
            return

        self._send_notification(
            "session/cancel",
            {"sessionId": self._state.current_session.session_id},
        )

    @property
    def is_running(self) -> bool:
        """Check if the agent process is running."""
        return self._process is not None and self._process.poll() is None

    @property
    def session_id(self) -> str | None:
        """Get the current session ID, if any."""
        if self._state.current_session:
            return self._state.current_session.session_id
        return None

    @property
    def agent_info(self) -> dict[str, Any]:
        """Get the agent's info from initialization."""
        return self._state.agent_info

    @property
    def agent_capabilities(self) -> dict[str, Any]:
        """Get the agent's capabilities from initialization."""
        return self._state.agent_capabilities
