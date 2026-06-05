import base64
import json
import os
from collections.abc import AsyncGenerator
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import Depends
from fastapi import HTTPException
from fastapi import status

from onyx.db.models import User
from shared_configs.contextvars import CURRENT_USER_ID_CONTEXTVAR


class BasicAuthenticationError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


class OnyxJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder that converts datetime and UUID objects to strings."""

    def default(self, obj: Any) -> Any:  # ty: ignore[invalid-method-override]
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


def set_current_user_id_dependency(
    user_dependency: Callable[..., Any],
) -> Callable[..., AsyncGenerator[None, None]]:
    """Build a dependency that pins CURRENT_USER_ID_CONTEXTVAR to the request's user.

    Must be set in the event-loop context (not inside the StreamingResponse
    generator): Starlette drives a sync streaming generator via
    ``iterate_in_threadpool``, where anyio does a fresh ``copy_context()`` per
    ``next()`` — a ``.set()`` inside the generator survives only the first chunk,
    and the matching ``.reset()`` raises (different context). Setting in the
    async dependency's event-loop context propagates into every per-step copy
    and resets cleanly, covering all branches of the endpoint (incl. multi-model
    and non-streaming).

    ``user_dependency`` is the endpoint's own user-providing auth dependency, so
    the var is set only after auth succeeds.
    """

    async def _dep(
        user: User = Depends(user_dependency),
    ) -> AsyncGenerator[None, None]:
        token = CURRENT_USER_ID_CONTEXTVAR.set(str(user.id))
        try:
            yield
        finally:
            CURRENT_USER_ID_CONTEXTVAR.reset(token)

    return _dep
