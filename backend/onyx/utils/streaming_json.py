"""Partial parsing of a JSON object that arrives in fragments."""

from pydantic import JsonValue
from pydantic_core import from_json


def parse_partial_object(text: str) -> dict[str, JsonValue]:
    """Parse the start of a JSON object with Pydantic's partial JSON mode.

    Escapes, including surrogate pairs split across fragments, decode exactly
    as in a complete parse. Incomplete strings are kept up to their last
    complete character; incomplete numbers and literals are left out until
    they complete. Text that is not an object yet returns an empty dict.

    Raises ValueError when the text cannot be the start of a valid JSON document.
    """
    if not text.strip():
        return {}
    try:
        parsed = from_json(text, allow_partial="trailing-strings")
    except TypeError as error:
        # Text that cannot be encoded as UTF-8 is invalid JSON input.
        raise ValueError(str(error)) from error
    return parsed if isinstance(parsed, dict) else {}


def appended_text(
    previous: dict[str, JsonValue], current: dict[str, JsonValue]
) -> dict[str, str]:
    """Return the text added to each top-level string field since `previous`.

    A repeated key can replace a value; an append-only stream skips it.
    """
    added: dict[str, str] = {}
    for key, value in current.items():
        if not isinstance(value, str):
            continue
        before = previous.get(key)
        before_text = before if isinstance(before, str) else ""
        if len(value) > len(before_text) and value.startswith(before_text):
            added[key] = value[len(before_text) :]
    return added
