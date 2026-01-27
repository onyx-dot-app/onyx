"""Simple packet logger for build mode debugging.

Logs the raw JSON of every packet emitted during build mode.

Log output: backend/onyx/server/features/build/packets.log
"""

import json
import logging
import os
from pathlib import Path
from typing import Any


class PacketLogger:
    """Simple packet logger - outputs raw JSON for each packet."""

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
        self._enabled = os.getenv("LOG_LEVEL", "").upper() == "DEBUG"
        self._logger: logging.Logger | None = None

        if self._enabled:
            self._setup_logger()

    def _setup_logger(self) -> None:
        """Set up the file handler for packet logging."""
        # Log to backend/onyx/server/features/build/packets.log
        build_dir = Path(__file__).parents[1]
        log_file = build_dir / "packets.log"

        self._logger = logging.getLogger("build.packets")
        self._logger.setLevel(logging.DEBUG)
        self._logger.propagate = False

        self._logger.handlers.clear()

        handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter("%(message)s"))

        self._logger.addHandler(handler)

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
            self._logger.debug(f"\n=== {packet_type} ===\n{output}")
        except Exception:
            self._logger.debug(f"\n=== {packet_type} ===\n{payload}")

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
            self._logger.debug(f"\n=== {label} ===\n{output}")
        except Exception:
            self._logger.debug(f"\n=== {label} ===\n{data}")


# Singleton instance
_packet_logger: PacketLogger | None = None


def get_packet_logger() -> PacketLogger:
    """Get the singleton packet logger instance."""
    global _packet_logger
    if _packet_logger is None:
        _packet_logger = PacketLogger()
    return _packet_logger
