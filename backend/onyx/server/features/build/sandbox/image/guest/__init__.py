"""Immutable Craft guest command package."""

from pathlib import Path

PROTOCOL_VERSION = 2
MAX_HISTORY_ARCHIVE_BYTES = 1024 * 1024 * 1024
SESSIONS_ROOT = Path("/workspace/sessions")
OPENCODE_DATA_HOME = Path("/workspace/opencode-data")
