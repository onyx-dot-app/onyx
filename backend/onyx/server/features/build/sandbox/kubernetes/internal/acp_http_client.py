"""HTTP-based ACP client for communicating with sandbox agents in Kubernetes pods.

This client implements the ACP (Agent Client Protocol) over HTTP/SSE instead of
stdin/stdout, enabling communication with sandbox agents running in separate pods.

Usage:
    client = ACPHttpClient("http://sandbox-abc123.onyx-sandboxes.svc.cluster.local:8081")
    client.initialize()
    for event in client.send_message("What files are here?"):
        print(event)
    client.close()
"""

import json
from collections.abc import Generator
from typing import Any

import httpx
from acp.schema import AgentMessageChunk
from acp.schema import AgentPlanUpdate
from acp.schema import AgentThoughtChunk
from acp.schema import CurrentModeUpdate
from acp.schema import Error
from acp.schema import PromptResponse
from acp.schema import ToolCallProgress
from acp.schema import ToolCallStart
from pydantic import ValidationError

from onyx.utils.logger import setup_logger

logger = setup_logger()

# ACP Protocol version
ACP_PROTOCOL_VERSION = 1

# Default client info
DEFAULT_CLIENT_INFO = {
    "name": "onyx-sandbox-k8s",
    "title": "Onyx Sandbox Agent Client (Kubernetes)",
    "version": "1.0.0",
}

# Union type for all possible events from send_message
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


class ACPHttpClient:
    """HTTP-based ACP client for communicating with sandbox agents in Kubernetes pods.

    Implements JSON-RPC 2.0 over HTTP as specified by ACP, with Server-Sent Events (SSE)
    for streaming responses.

    The sandbox pod exposes an HTTP server (opencode serve) that accepts ACP requests.
    """

    def __init__(
        self,
        base_url: str,
        client_info: dict[str, Any] | None = None,
        client_capabilities: dict[str, Any] | None = None,
        timeout: float = 300.0,
    ) -> None:
        """Initialize the HTTP-based ACP client.

        Args:
            base_url: Base URL for the sandbox agent HTTP server (e.g.,
                "http://sandbox-abc123.onyx-sandboxes.svc.cluster.local:8081")
            client_info: Client identification info (name, title, version)
            client_capabilities: Client capabilities to advertise
            timeout: Request timeout in seconds
        """
        self._base_url = base_url.rstrip("/")
        self._client_info = client_info or DEFAULT_CLIENT_INFO
        self._client_capabilities = client_capabilities or {
            "fs": {
                "readTextFile": True,
                "writeTextFile": True,
            },
            "terminal": True,
        }
        self._timeout = timeout
        self._http_client = httpx.Client(timeout=timeout)
        self._session_id: str | None = None
        self._initialized = False
        self._agent_capabilities: dict[str, Any] = {}
        self._agent_info: dict[str, Any] = {}

    def initialize(self, cwd: str = "/workspace") -> str:
        """Initialize ACP connection and create a session.

        Args:
            cwd: Working directory for the agent session

        Returns:
            The session ID

        Raises:
            RuntimeError: If initialization fails
        """
        if self._initialized and self._session_id:
            return self._session_id

        # Send initialize request
        init_params = {
            "protocolVersion": ACP_PROTOCOL_VERSION,
            "clientCapabilities": self._client_capabilities,
            "clientInfo": self._client_info,
        }

        try:
            init_response = self._http_client.post(
                f"{self._base_url}/acp/initialize",
                json=init_params,
            )
            init_response.raise_for_status()
            init_result = init_response.json()

            self._initialized = True
            self._agent_capabilities = init_result.get("agentCapabilities", {})
            self._agent_info = init_result.get("agentInfo", {})

            logger.debug(f"ACP initialized with agent: {self._agent_info}")

        except httpx.HTTPError as e:
            raise RuntimeError(f"Failed to initialize ACP connection: {e}") from e

        # Create a new session
        session_params = {
            "cwd": cwd,
            "mcpServers": [],
        }

        try:
            session_response = self._http_client.post(
                f"{self._base_url}/acp/session/new",
                json=session_params,
            )
            session_response.raise_for_status()
            session_result = session_response.json()

            self._session_id = session_result.get("sessionId")
            if not self._session_id:
                raise RuntimeError("No session ID returned from session/new")

            logger.debug(f"ACP session created: {self._session_id}")
            return self._session_id

        except httpx.HTTPError as e:
            raise RuntimeError(f"Failed to create ACP session: {e}") from e

    def send_message(
        self,
        message: str,
        timeout: float | None = None,
    ) -> Generator[ACPEvent, None, None]:
        """Send a message and stream response events via SSE.

        Args:
            message: The message content to send
            timeout: Optional timeout override

        Yields:
            Typed ACP schema event objects (ACPEvent union)

        Raises:
            RuntimeError: If no session or prompt fails
        """
        if not self._session_id:
            raise RuntimeError("No active session. Call initialize() first.")

        # Build prompt content
        prompt_content = [{"type": "text", "text": message}]
        params = {
            "sessionId": self._session_id,
            "prompt": prompt_content,
        }

        request_timeout = timeout or self._timeout

        try:
            # Use streaming for SSE responses
            with self._http_client.stream(
                "POST",
                f"{self._base_url}/acp/session/{self._session_id}/prompt",
                json=params,
                timeout=request_timeout,
            ) as response:
                response.raise_for_status()

                # Process SSE stream
                for line in response.iter_lines():
                    if not line:
                        continue

                    # SSE format: "data: {...json...}"
                    if line.startswith("data: "):
                        data_str = line[6:]  # Strip "data: " prefix
                        if data_str == "[DONE]":
                            break

                        try:
                            event_data = json.loads(data_str)
                            for event in self._process_event(event_data):
                                yield event
                        except json.JSONDecodeError as e:
                            logger.warning(f"Failed to parse SSE event: {e}")
                            continue

                    # Handle event type lines
                    elif line.startswith("event: "):
                        # Event type is specified, next data line will have payload
                        continue

        except httpx.TimeoutException:
            yield Error(code=-1, message="Request timeout")
        except httpx.HTTPStatusError as e:
            yield Error(code=e.response.status_code, message=str(e))
        except httpx.HTTPError as e:
            yield Error(code=-1, message=f"HTTP error: {e}")

    def _process_event(
        self, event_data: dict[str, Any]
    ) -> Generator[ACPEvent, None, None]:
        """Process an event from the SSE stream and yield typed ACP schema objects.

        Args:
            event_data: The parsed JSON event data

        Yields:
            Typed ACP schema objects
        """
        # Check if this is a final response
        if "result" in event_data:
            result = event_data["result"]
            try:
                yield PromptResponse.model_validate(result)
            except ValidationError:
                pass
            return

        # Check for error response
        if "error" in event_data:
            error = event_data["error"]
            yield Error(
                code=error.get("code", -1),
                message=error.get("message", "Unknown error"),
            )
            return

        # Handle session update notifications
        update_type = event_data.get("sessionUpdate")
        if not update_type:
            # Try to get from params for notification format
            params = event_data.get("params", {})
            update = params.get("update", event_data)
            update_type = update.get("sessionUpdate")
            if update_type:
                event_data = update

        if update_type == "agent_message_chunk":
            try:
                yield AgentMessageChunk.model_validate(event_data)
            except ValidationError:
                pass

        elif update_type == "agent_thought_chunk":
            try:
                yield AgentThoughtChunk.model_validate(event_data)
            except ValidationError:
                pass

        elif update_type == "user_message_chunk":
            pass  # Echo of user message - skip

        elif update_type == "tool_call":
            try:
                yield ToolCallStart.model_validate(event_data)
            except ValidationError:
                pass

        elif update_type == "tool_call_update":
            try:
                yield ToolCallProgress.model_validate(event_data)
            except ValidationError:
                pass

        elif update_type == "plan":
            try:
                yield AgentPlanUpdate.model_validate(event_data)
            except ValidationError:
                pass

        elif update_type == "available_commands_update":
            pass  # Skip command updates

        elif update_type == "current_mode_update":
            try:
                yield CurrentModeUpdate.model_validate(event_data)
            except ValidationError:
                pass

        elif update_type == "session_info_update":
            pass  # Skip session info updates

        # Unknown update types are silently skipped

    def cancel(self) -> None:
        """Cancel the current operation."""
        if not self._session_id:
            return

        try:
            self._http_client.post(
                f"{self._base_url}/acp/session/{self._session_id}/cancel",
            )
        except httpx.HTTPError as e:
            logger.warning(f"Failed to cancel operation: {e}")

    def close(self) -> None:
        """Close the HTTP client and cleanup resources."""
        self._http_client.close()
        self._session_id = None
        self._initialized = False

    def health_check(self, timeout: float = 5.0) -> bool:
        """Check if the agent server is healthy.

        Args:
            timeout: Health check timeout

        Returns:
            True if healthy, False otherwise
        """
        try:
            response = self._http_client.get(
                f"{self._base_url}/global/health",
                timeout=timeout,
            )
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    @property
    def is_initialized(self) -> bool:
        """Check if the client is initialized."""
        return self._initialized

    @property
    def session_id(self) -> str | None:
        """Get the current session ID, if any."""
        return self._session_id

    @property
    def agent_info(self) -> dict[str, Any]:
        """Get the agent's info from initialization."""
        return self._agent_info

    @property
    def agent_capabilities(self) -> dict[str, Any]:
        """Get the agent's capabilities from initialization."""
        return self._agent_capabilities

    def __enter__(self) -> "ACPHttpClient":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit - ensures cleanup."""
        self.close()
