"""Comprehensive packet and ACP event logger for build mode debugging.

Logs all packets, JSON-RPC messages, and ACP events during build mode streaming.
Provides detailed tracing for the entire agent loop and communication flow.

Log output locations (in priority order):
1. /var/log/onyx/packets.log (for Docker - mounted to host via docker-compose volumes)
2. backend/log/packets.log (for local dev without Docker)
3. backend/onyx/server/features/build/packets.log (fallback)

Enable logging by setting LOG_LEVEL=DEBUG or BUILD_PACKET_LOGGING=true.

Features:
- Rotating log with max 5000 lines (configurable via BUILD_PACKET_LOG_MAX_LINES)
- Automatically trims oldest entries when limit is exceeded
- Visual separators between message streams for easy reading
"""

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any
from uuid import UUID

# Default max lines to keep in the log file (acts like a deque)
DEFAULT_MAX_LOG_LINES = 5000


class PacketLogger:
    """Comprehensive logger for ACP/OpenCode communication and packet streaming.

    Logs:
    - All JSON-RPC requests sent to the agent
    - All JSON-RPC responses/notifications received from the agent
    - All ACP events emitted during streaming
    - Session and sandbox lifecycle events
    - Timing information for debugging performance

    The log file is kept to a maximum number of lines (default 5000) to prevent
    unbounded growth. When the limit is exceeded, the oldest lines are trimmed.
    """

    _instance: "PacketLogger | None" = None
    _initialized: bool

    def __new__(cls) -> "PacketLogger":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return

        self._initialized = True
        # Enable via LOG_LEVEL=DEBUG or BUILD_PACKET_LOGGING=true
        log_level = os.getenv("LOG_LEVEL", "").upper()
        packet_logging = os.getenv("BUILD_PACKET_LOGGING", "").lower()
        self._enabled = log_level == "DEBUG" or packet_logging in ("true", "1", "yes")
        self._logger: logging.Logger | None = None
        self._log_file_path: Path | None = None
        self._session_start_times: dict[str, float] = {}

        # Max lines to keep in log file
        try:
            self._max_lines = int(
                os.getenv("BUILD_PACKET_LOG_MAX_LINES", str(DEFAULT_MAX_LOG_LINES))
            )
        except ValueError:
            self._max_lines = DEFAULT_MAX_LOG_LINES

        # Lock for thread-safe file operations
        self._file_lock = threading.Lock()

        # Track approximate line count to avoid reading file too often
        self._approx_line_count = 0
        self._lines_since_last_trim = 0
        # Trim every N lines written to avoid constant file reads
        self._trim_interval = 500

        if self._enabled:
            self._setup_logger()

    def _get_log_file_path(self) -> Path:
        """Determine the best log file path based on environment.

        Priority:
        1. /var/log/onyx/packets.log - Docker environment (mounted to host)
        2. backend/log/packets.log - Local dev (same dir as other logs)
        3. backend/onyx/server/features/build/packets.log - Fallback
        """
        # Option 1: Docker environment - use /var/log/onyx which is mounted
        docker_log_dir = Path("/var/log/onyx")
        if docker_log_dir.exists() and docker_log_dir.is_dir():
            return docker_log_dir / "packets.log"

        # Option 2: Local dev - use backend/log directory (same as other debug logs)
        # Navigate from this file to backend/log
        backend_dir = Path(__file__).parents[4]  # up to backend/
        local_log_dir = backend_dir / "log"
        if local_log_dir.exists() and local_log_dir.is_dir():
            return local_log_dir / "packets.log"

        # Option 3: Fallback to build directory
        build_dir = Path(__file__).parents[1]
        return build_dir / "packets.log"

    def _setup_logger(self) -> None:
        """Set up the file handler for packet logging."""
        self._log_file_path = self._get_log_file_path()

        # Ensure parent directory exists
        self._log_file_path.parent.mkdir(parents=True, exist_ok=True)

        self._logger = logging.getLogger("build.packets")
        self._logger.setLevel(logging.DEBUG)
        self._logger.propagate = False

        self._logger.handlers.clear()

        # Use append mode
        handler = logging.FileHandler(self._log_file_path, mode="a", encoding="utf-8")
        handler.setLevel(logging.DEBUG)
        # Include timestamp in each log entry
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s.%(msecs)03d | %(message)s", "%Y-%m-%d %H:%M:%S"
            )
        )

        self._logger.addHandler(handler)

        # Initialize line count from existing file
        self._init_line_count()

    def _init_line_count(self) -> None:
        """Initialize the approximate line count from the existing log file."""
        if not self._log_file_path or not self._log_file_path.exists():
            self._approx_line_count = 0
            return

        try:
            with open(self._log_file_path, "r", encoding="utf-8", errors="ignore") as f:
                self._approx_line_count = sum(1 for _ in f)
        except Exception:
            self._approx_line_count = 0

    def _maybe_trim_log(self) -> None:
        """Trim the log file if it exceeds the max line limit.

        This is called periodically (every _trim_interval lines) to avoid
        reading the file on every write.
        """
        self._lines_since_last_trim += 1

        if self._lines_since_last_trim < self._trim_interval:
            return

        self._lines_since_last_trim = 0
        self._trim_log_file()

    def _trim_log_file(self) -> None:
        """Trim the log file to keep only the last max_lines."""
        if not self._log_file_path or not self._log_file_path.exists():
            return

        with self._file_lock:
            try:
                # Read all lines
                with open(
                    self._log_file_path, "r", encoding="utf-8", errors="ignore"
                ) as f:
                    lines = f.readlines()

                current_count = len(lines)
                self._approx_line_count = current_count

                # If under limit, nothing to do
                if current_count <= self._max_lines:
                    return

                # Keep only the last max_lines
                lines_to_keep = lines[-self._max_lines :]

                # Close the logger's file handler temporarily
                if self._logger:
                    for handler in self._logger.handlers:
                        handler.close()

                # Rewrite the file with trimmed content
                with open(self._log_file_path, "w", encoding="utf-8") as f:
                    f.writelines(lines_to_keep)

                # Reopen the handler
                if self._logger:
                    self._logger.handlers.clear()
                    handler = logging.FileHandler(
                        self._log_file_path, mode="a", encoding="utf-8"
                    )
                    handler.setLevel(logging.DEBUG)
                    handler.setFormatter(
                        logging.Formatter(
                            "%(asctime)s.%(msecs)03d | %(message)s", "%Y-%m-%d %H:%M:%S"
                        )
                    )
                    self._logger.addHandler(handler)

                self._approx_line_count = len(lines_to_keep)

            except Exception:
                pass  # Silently ignore errors during trim

    def clear_log_file(self) -> None:
        """Clear the log file contents.

        Note: With the rotating log approach, this is optional. The log will
        automatically trim itself. But this can still be useful to start fresh.
        """
        if not self._enabled or not self._log_file_path:
            return

        with self._file_lock:
            try:
                # Close the logger's file handler temporarily
                if self._logger:
                    for handler in self._logger.handlers:
                        handler.close()

                # Truncate the file
                with open(self._log_file_path, "w", encoding="utf-8") as f:
                    f.write("")  # Empty the file

                # Reopen the handler
                if self._logger:
                    self._logger.handlers.clear()
                    handler = logging.FileHandler(
                        self._log_file_path, mode="a", encoding="utf-8"
                    )
                    handler.setLevel(logging.DEBUG)
                    handler.setFormatter(
                        logging.Formatter(
                            "%(asctime)s.%(msecs)03d | %(message)s", "%Y-%m-%d %H:%M:%S"
                        )
                    )
                    self._logger.addHandler(handler)

                self._approx_line_count = 0
                self._lines_since_last_trim = 0

            except Exception:
                pass  # Silently ignore errors

    @property
    def is_enabled(self) -> bool:
        """Check if logging is enabled."""
        return self._enabled and self._logger is not None

    def _format_uuid(self, value: Any) -> str:
        """Format UUID for logging (shortened for readability)."""
        if isinstance(value, UUID):
            return str(value)[:8]
        if isinstance(value, str) and len(value) >= 8:
            return value[:8]
        return str(value)

    def _write_log(self, message: str) -> None:
        """Internal method to write a log message and trigger trim check.

        Args:
            message: The formatted log message
        """
        if not self._logger:
            return

        self._logger.debug(message)
        self._maybe_trim_log()

    def log(self, packet_type: str, payload: dict[str, Any] | None = None) -> None:
        """Log a packet as JSON.

        Args:
            packet_type: The type of packet
            payload: The packet payload
        """
        if not self._enabled or not self._logger:
            return

        try:
            output = json.dumps(payload, indent=2, default=str) if payload else "{}"
            self._write_log(f"[PACKET] {packet_type}\n{output}")
        except Exception:
            self._write_log(f"[PACKET] {packet_type}\n{payload}")

    def log_raw(self, label: str, data: Any) -> None:
        """Log raw data with a label.

        Args:
            label: A label for this log entry
            data: Any data to log
        """
        if not self._enabled or not self._logger:
            return

        try:
            if isinstance(data, (dict, list)):
                output = json.dumps(data, indent=2, default=str)
            else:
                output = str(data)
            self._write_log(f"[RAW] {label}\n{output}")
        except Exception:
            self._write_log(f"[RAW] {label}\n{data}")

    # =========================================================================
    # JSON-RPC Communication Logging
    # =========================================================================

    def log_jsonrpc_request(
        self,
        method: str,
        request_id: int | None,
        params: dict[str, Any] | None = None,
        context: str = "",
    ) -> None:
        """Log a JSON-RPC request being sent to the agent.

        Args:
            method: The JSON-RPC method name
            request_id: The request ID (None for notifications)
            params: The request parameters
            context: Additional context (e.g., "local", "k8s")
        """
        if not self._enabled or not self._logger:
            return

        try:
            req_type = "REQUEST" if request_id is not None else "NOTIFICATION"
            ctx_prefix = f"[{context}] " if context else ""
            params_str = json.dumps(params, indent=2, default=str) if params else "{}"
            id_str = f" id={request_id}" if request_id is not None else ""
            self._write_log(
                f"{ctx_prefix}[JSONRPC-OUT] {req_type} {method}{id_str}\n{params_str}"
            )
        except Exception as e:
            self._write_log(f"[JSONRPC-OUT] {method} (logging error: {e})")

    def log_jsonrpc_response(
        self,
        request_id: int | None,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        context: str = "",
    ) -> None:
        """Log a JSON-RPC response received from the agent.

        Args:
            request_id: The request ID this is responding to
            result: The result payload (if success)
            error: The error payload (if error)
            context: Additional context (e.g., "local", "k8s")
        """
        if not self._enabled or not self._logger:
            return

        try:
            ctx_prefix = f"[{context}] " if context else ""
            id_str = f" id={request_id}" if request_id is not None else ""
            if error:
                error_str = json.dumps(error, indent=2, default=str)
                self._write_log(
                    f"{ctx_prefix}[JSONRPC-IN] RESPONSE{id_str} ERROR\n{error_str}"
                )
            else:
                result_str = (
                    json.dumps(result, indent=2, default=str) if result else "{}"
                )
                self._write_log(
                    f"{ctx_prefix}[JSONRPC-IN] RESPONSE{id_str}\n{result_str}"
                )
        except Exception as e:
            self._write_log(f"[JSONRPC-IN] RESPONSE (logging error: {e})")

    def log_jsonrpc_notification(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        context: str = "",
    ) -> None:
        """Log a JSON-RPC notification received from the agent.

        Args:
            method: The notification method name
            params: The notification parameters
            context: Additional context (e.g., "local", "k8s")
        """
        if not self._enabled or not self._logger:
            return

        try:
            ctx_prefix = f"[{context}] " if context else ""
            params_str = json.dumps(params, indent=2, default=str) if params else "{}"
            self._write_log(
                f"{ctx_prefix}[JSONRPC-IN] NOTIFICATION {method}\n{params_str}"
            )
        except Exception as e:
            self._write_log(f"[JSONRPC-IN] NOTIFICATION {method} (logging error: {e})")

    def log_jsonrpc_raw_message(
        self,
        direction: str,
        message: dict[str, Any] | str,
        context: str = "",
    ) -> None:
        """Log a raw JSON-RPC message (for debugging parsing issues).

        Args:
            direction: "IN" or "OUT"
            message: The raw message (dict or string)
            context: Additional context
        """
        if not self._enabled or not self._logger:
            return

        try:
            ctx_prefix = f"[{context}] " if context else ""
            if isinstance(message, dict):
                msg_str = json.dumps(message, indent=2, default=str)
            else:
                msg_str = str(message)
            self._write_log(f"{ctx_prefix}[JSONRPC-RAW-{direction}]\n{msg_str}")
        except Exception as e:
            self._write_log(f"[JSONRPC-RAW-{direction}] (logging error: {e})")

    # =========================================================================
    # ACP Event Logging
    # =========================================================================

    def log_acp_event(
        self,
        event_type: str,
        event_data: dict[str, Any],
        sandbox_id: UUID | str | None = None,
        session_id: UUID | str | None = None,
    ) -> None:
        """Log an ACP event being emitted.

        Args:
            event_type: The ACP event type (e.g., "agent_message_chunk")
            event_data: The full event data
            sandbox_id: The sandbox ID (optional, for context)
            session_id: The session ID (optional, for context)
        """
        if not self._enabled or not self._logger:
            return

        try:
            ctx_parts = []
            if sandbox_id:
                ctx_parts.append(f"sandbox={self._format_uuid(sandbox_id)}")
            if session_id:
                ctx_parts.append(f"session={self._format_uuid(session_id)}")
            ctx = f" ({', '.join(ctx_parts)})" if ctx_parts else ""

            # For message chunks, show truncated content for readability
            display_data = event_data.copy()
            if event_type in ("agent_message_chunk", "agent_thought_chunk"):
                content = display_data.get("content", {})
                if isinstance(content, dict) and "text" in content:
                    text = content.get("text", "")
                    if len(text) > 200:
                        display_data["content"] = {
                            **content,
                            "text": text[:200] + f"... ({len(text)} chars total)",
                        }

            event_str = json.dumps(display_data, indent=2, default=str)
            self._write_log(f"[ACP-EVENT] {event_type}{ctx}\n{event_str}")
        except Exception as e:
            self._write_log(f"[ACP-EVENT] {event_type} (logging error: {e})")

    def log_acp_event_yielded(
        self,
        event_type: str,
        event_obj: Any,
        sandbox_id: UUID | str | None = None,
        session_id: UUID | str | None = None,
    ) -> None:
        """Log an ACP event object being yielded from the generator.

        Args:
            event_type: The ACP event type
            event_obj: The Pydantic event object
            sandbox_id: The sandbox ID (optional)
            session_id: The session ID (optional)
        """
        if not self._enabled or not self._logger:
            return

        try:
            if hasattr(event_obj, "model_dump"):
                event_data = event_obj.model_dump(mode="json", by_alias=True)
            else:
                event_data = {"raw": str(event_obj)}
            self.log_acp_event(event_type, event_data, sandbox_id, session_id)
        except Exception as e:
            self._write_log(f"[ACP-EVENT] {event_type} (logging error: {e})")

    # =========================================================================
    # Session and Sandbox Lifecycle Logging
    # =========================================================================

    def log_session_start(
        self,
        session_id: UUID | str,
        sandbox_id: UUID | str,
        message_preview: str = "",
    ) -> None:
        """Log the start of a message streaming session.

        Args:
            session_id: The session ID
            sandbox_id: The sandbox ID
            message_preview: First 100 chars of the user message
        """
        if not self._enabled or not self._logger:
            return

        session_key = str(session_id)
        self._session_start_times[session_key] = time.time()

        preview = (
            message_preview[:100] + "..."
            if len(message_preview) > 100
            else message_preview
        )
        self._write_log(
            f"[SESSION-START] session={self._format_uuid(session_id)} "
            f"sandbox={self._format_uuid(sandbox_id)}\n"
            f"  message: {preview}"
        )

    def log_session_end(
        self,
        session_id: UUID | str,
        success: bool = True,
        error: str | None = None,
        events_count: int = 0,
    ) -> None:
        """Log the end of a message streaming session.

        Args:
            session_id: The session ID
            success: Whether the session completed successfully
            error: Error message if failed
            events_count: Number of events emitted
        """
        if not self._enabled or not self._logger:
            return

        session_key = str(session_id)
        start_time = self._session_start_times.pop(session_key, None)
        duration_ms = (time.time() - start_time) * 1000 if start_time else 0

        status = "SUCCESS" if success else "FAILED"
        error_str = f"\n  error: {error}" if error else ""
        self._write_log(
            f"[SESSION-END] session={self._format_uuid(session_id)} "
            f"status={status} duration={duration_ms:.0f}ms events={events_count}"
            f"{error_str}"
        )

    def log_acp_client_start(
        self,
        sandbox_id: UUID | str,
        session_id: UUID | str,
        cwd: str,
        context: str = "",
    ) -> None:
        """Log ACP client initialization.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID
            cwd: Working directory
            context: "local" or "k8s"
        """
        if not self._enabled or not self._logger:
            return

        ctx_prefix = f"[{context}] " if context else ""
        self._write_log(
            f"{ctx_prefix}[ACP-CLIENT-START] "
            f"sandbox={self._format_uuid(sandbox_id)} "
            f"session={self._format_uuid(session_id)}\n"
            f"  cwd: {cwd}"
        )

    def log_acp_client_stop(
        self,
        sandbox_id: UUID | str,
        session_id: UUID | str,
        context: str = "",
    ) -> None:
        """Log ACP client shutdown.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID
            context: "local" or "k8s"
        """
        if not self._enabled or not self._logger:
            return

        ctx_prefix = f"[{context}] " if context else ""
        self._write_log(
            f"{ctx_prefix}[ACP-CLIENT-STOP] "
            f"sandbox={self._format_uuid(sandbox_id)} "
            f"session={self._format_uuid(session_id)}"
        )

    # =========================================================================
    # Streaming State Logging
    # =========================================================================

    def log_streaming_state_update(
        self,
        session_id: UUID | str,
        state_type: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Log streaming state changes.

        Args:
            session_id: The session ID
            state_type: Type of state change (e.g., "chunk_accumulated", "saved_to_db")
            details: Additional details
        """
        if not self._enabled or not self._logger:
            return

        try:
            details_str = ""
            if details:
                details_str = "\n" + json.dumps(details, indent=2, default=str)
            self._write_log(
                f"[STREAMING-STATE] session={self._format_uuid(session_id)} "
                f"type={state_type}{details_str}"
            )
        except Exception as e:
            self._write_log(f"[STREAMING-STATE] {state_type} (logging error: {e})")

    def log_sse_emit(
        self,
        event_type: str,
        session_id: UUID | str | None = None,
    ) -> None:
        """Log SSE event being emitted to frontend.

        Args:
            event_type: The event type being emitted
            session_id: The session ID
        """
        if not self._enabled or not self._logger:
            return

        session_str = f" session={self._format_uuid(session_id)}" if session_id else ""
        self._write_log(f"[SSE-EMIT] {event_type}{session_str}")


# Singleton instance
_packet_logger: PacketLogger | None = None


def get_packet_logger() -> PacketLogger:
    """Get the singleton packet logger instance."""
    global _packet_logger
    if _packet_logger is None:
        _packet_logger = PacketLogger()
    return _packet_logger


def log_separator(label: str = "") -> None:
    """Log a visual separator for readability in the log file.

    Args:
        label: Optional label for the separator
    """
    logger = get_packet_logger()
    if not logger.is_enabled or not logger._logger:
        return

    separator = "=" * 80
    if label:
        logger._write_log(f"\n{separator}\n{label}\n{separator}")
    else:
        logger._write_log(f"\n{separator}")
