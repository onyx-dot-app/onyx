"""Incremental parsing of a JSON object that arrives in fragments."""

from pydantic import JsonValue
from pydantic_core import from_json


class StreamingJsonParser:
    """Parse a streamed JSON object and report text added to its string fields.

    Each fragment re-parses the accumulated text with Pydantic's partial JSON
    mode, so escapes, including surrogate pairs split across fragments, decode
    exactly as in a complete parse. Incomplete strings are reported up to their
    last complete character; incomplete numbers and literals are left out until
    they complete.
    """

    def __init__(self) -> None:
        self._text = ""
        self._value: dict[str, JsonValue] = {}

    def feed(self, fragment: str) -> dict[str, str]:
        """Add a fragment and return the new text of each top-level string field.

        Raises ValueError when the accumulated text cannot be the start of a
        valid JSON document.
        """
        self._text += fragment
        if not self._text.strip():
            return {}
        try:
            parsed = from_json(self._text, allow_partial="trailing-strings")
        except TypeError as error:
            # Text that cannot be encoded as UTF-8 is invalid JSON input.
            raise ValueError(str(error)) from error
        if not isinstance(parsed, dict):
            return {}
        deltas: dict[str, str] = {}
        for key, value in parsed.items():
            previous = self._value.get(key)
            if not isinstance(value, str):
                continue
            previous_text = previous if isinstance(previous, str) else ""
            # A repeated key can replace a value; an append-only stream skips it.
            if len(value) > len(previous_text) and value.startswith(previous_text):
                deltas[key] = value[len(previous_text) :]
        self._value = parsed
        return deltas

    def snapshot(self) -> dict[str, JsonValue]:
        """Return the object parsed so far."""
        return dict(self._value)
