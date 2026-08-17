from collections.abc import Iterable

REDACTED_VALUE = "[REDACTED]"
_MINIMUM_REDACTED_VALUE_LENGTH = 3


def scrub_sensitive_values(message: str, values: Iterable[str | None]) -> str:
    """Replace known sensitive values without corrupting common short text."""
    sensitive_values = sorted(
        {
            value
            for value in values
            if value and len(value) >= _MINIMUM_REDACTED_VALUE_LENGTH
        },
        key=len,
        reverse=True,
    )
    for value in sensitive_values:
        message = message.replace(value, REDACTED_VALUE)
    return message
