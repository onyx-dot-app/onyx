"""Shared data masking utilities for tracing processors."""

import os
import re
from typing import Any

# Set loosely because some tool call results may be very long.
# Ideally we don't pass those to the LLM but it's fine if we want to trace them in full.
MASKING_LENGTH = int(os.environ.get("TRACING_MASKING_LENGTH", "500000"))


def _truncate_str(s: str) -> str:
    """Truncate a string that exceeds MASKING_LENGTH."""
    tail = MASKING_LENGTH // 5
    head = MASKING_LENGTH - tail
    # Handle edge case where tail is 0 (when MASKING_LENGTH < 5)
    # s[-0:] returns the entire string, so we must check explicitly
    tail_part = s[-tail:] if tail > 0 else ""
    return f"{s[:head]}...{tail_part}[TRUNCATED {len(s)} chars to {MASKING_LENGTH}]"


def mask_sensitive_data(data: Any) -> Any:
    """Mask data if it exceeds the maximum length threshold or contains sensitive information.

    Handles:
    - Dictionaries: recursively masks values, redacts keys containing 'private_key' or 'authorization'
    - Lists: recursively masks each item
    - Strings: redacts private_key patterns, Authorization Bearer tokens, truncates long strings
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
                masked_dict[key] = mask_sensitive_data(value)
        return masked_dict

    # Handle lists recursively
    if isinstance(data, list):
        return [mask_sensitive_data(item) for item in data]

    # Handle strings
    if isinstance(data, str):
        # Mask private_key patterns
        if "private_key" in data.lower():
            return "***REDACTED***"

        # Mask Authorization: Bearer tokens
        # Pattern matches "Authorization: Bearer <token>" or "authorization: bearer <token>"
        if re.search(r"authorization:\s*bearer\s+\S+", data, re.IGNORECASE):
            data = re.sub(
                r"(authorization:\s*bearer\s+)\S+",
                r"\1***REDACTED***",
                data,
                flags=re.IGNORECASE,
            )

        if len(data) <= MASKING_LENGTH:
            return data
        return _truncate_str(data)

    # For other types, check length
    if len(str(data)) <= MASKING_LENGTH:
        return data
    return _truncate_str(str(data))
