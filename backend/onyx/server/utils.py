import base64
import json
import os
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from fastapi import status


class BasicAuthenticationError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


class OnyxJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder that converts datetime and UUID objects to strings."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, UUID):
            return str(obj)
        return super().default(obj)


def get_json_line(
    json_dict: dict[str, Any], encoder: type[json.JSONEncoder] = OnyxJSONEncoder
) -> str:
    """
    Convert a dictionary to a JSON string with custom type handling, and add a newline.

    Args:
        json_dict: The dictionary to be converted to JSON.
        encoder: JSON encoder class to use, defaults to OnyxJSONEncoder.

    Returns:
        A JSON string representation of the input dictionary with a newline character.
    """
    return json.dumps(json_dict, cls=encoder) + "\n"


def make_short_id() -> str:
    """Fast way to generate a random 8 character id ... useful for tagging data
    to trace it through a flow. This is definitely not guaranteed to be unique and is
    targeted at the stated use case."""
    return base64.b32encode(os.urandom(5)).decode("utf-8")[:8]  # 5 bytes → 8 chars
