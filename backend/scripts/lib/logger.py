from __future__ import annotations

import logging
import os
import sys

# Detect CI environment
IS_CI = os.getenv("CI", "").lower() == "true"
IS_DEBUG = os.getenv("DEBUG", "").lower() == "true"

# ANSI color codes for local terminal
GRAY = "\033[90m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"


class CIFormatter(logging.Formatter):
    """
    Formatter that emits GitHub Actions workflow commands in CI,
    or colored output locally.
    """

    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        metadata = getattr(record, "extra", {})

        # Use standard extra fields as GitHub Actions metadata
        meta_fields = ["file", "line", "col", "endLine", "endColumn"]
        metadata = {k: getattr(record, k) for k in meta_fields if hasattr(record, k)}

        if IS_CI and record.levelno >= logging.WARNING:
            command = "error" if record.levelno >= logging.ERROR else "warning"
            meta_str = ",".join(f"{k}={v}" for k, v in metadata.items())
            if meta_str:
                return f"::{command} {meta_str}::{msg}"
            else:
                return f"::{command}::{msg}"

        # Local colored output
        if record.levelno >= logging.ERROR:
            return f"{RED}Error:{RESET} {msg}"
        elif record.levelno >= logging.WARNING:
            return f"{YELLOW}Warning:{RESET} {msg}"
        elif record.levelno >= logging.INFO:
            return f"{CYAN}Info:{RESET} {msg}"
        elif record.levelno >= logging.DEBUG:
            return f"{GRAY}Debug:{RESET} {msg}"
        return msg


def getLogger(name: str | None = None, level: int | None = None) -> logging.Logger:
    """
    Get a CI-aware logger.
    """
    logger = logging.getLogger(name)
    if level is None:
        level = logging.DEBUG if IS_DEBUG else logging.INFO
    logger.setLevel(level)

    if not logger.hasHandlers():
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(CIFormatter())
        logger.addHandler(handler)

    return logger
