"""Shared data masking utilities for tracing processors."""

import os
import re
from typing import Any

# Set loosely because some tool call results may be very long.
# Ideally we don't pass those to the LLM but it's fine if we want to trace them in full.
MASKING_LENGTH = int(os.environ.get("TRACING_MASKING_LENGTH", "500000"))
_PRIVATE_KEY = re.compile("private_key", re.IGNORECASE)
# "Authorization: Bearer <token>", in any case.
_BEARER_TOKEN = re.compile(r"(authorization:\s*bearer\s+)\S+", re.IGNORECASE)


def _truncate_str(s: str) -> str:
    """Truncate a string that exceeds MASKING_LENGTH."""
    tail = MASKING_LENGTH // 5
    head = MASKING_LENGTH - tail
    # Handle edge case where tail is 0 (when MASKING_LENGTH < 5)
    # s[-0:] returns the entire string, so we must check explicitly
    tail_part = s[-tail:] if tail > 0 else ""
    return f"{s[:head]}...{tail_part}[TRUNCATED {len(s)} chars to {MASKING_LENGTH}]"


def bound_trace_data(data: Any) -> Any:
    """Redact secrets in data and bound it to MASKING_LENGTH.

    Masking scans each whole string with one regular expression for each
    pattern, before the cut, and copies no strings when it finds no secret.

    Handles:
    - Dictionaries: recursively, and redacts the values of keys containing 'private_key' or 'authorization'
    - Lists: recursively
    - Strings: redacts private_key patterns and Authorization Bearer tokens, then truncates long strings
    - Other types: truncates if string representation exceeds threshold
    """
    # Handle dictionaries recursively
    if isinstance(data, dict):
        masked_dict = {}
        for key, value in data.items():
            # Mask private keys and authorization headers
            if isinstance(key, str) and (
                "private_key" in key.lower() or "authorization" in key.lower()
            ):
                masked_dict[key] = "***REDACTED***"
            else:
                masked_dict[key] = bound_trace_data(value)
        return masked_dict

    # Handle lists recursively
    if isinstance(data, list):
        return [bound_trace_data(item) for item in data]

    # Handle strings
    if isinstance(data, str):
        if _PRIVATE_KEY.search(data):
            return "***REDACTED***"
        data = _BEARER_TOKEN.sub(r"\1***REDACTED***", data)
        return _truncate_str(data) if len(data) > MASKING_LENGTH else data

    # For other types, check length
    if len(str(data)) <= MASKING_LENGTH:
        return data
    return _truncate_str(str(data))
