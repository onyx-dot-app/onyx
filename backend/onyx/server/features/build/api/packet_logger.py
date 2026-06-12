"""Packet logger for build mode debugging.

Logs packets and session lifecycle events during build mode streaming.

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
    """Logger for build mode packet streaming.

    Logs:
    - Packets emitted during streaming
    - Session lifecycle events with timing information

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


# Singleton instance
_packet_logger: PacketLogger | None = None


def get_packet_logger() -> PacketLogger:
    """Get the singleton packet logger instance."""
    global _packet_logger
    if _packet_logger is None:
        _packet_logger = PacketLogger()
    return _packet_logger
