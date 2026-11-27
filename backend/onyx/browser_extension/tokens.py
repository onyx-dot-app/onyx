"""Single-use tokens that open the Onyx extension's websocket
(`server/query_and_chat/chrome_browser.py`). The shared cache holds them,
since the websocket learns its tenant from the token."""

import secrets
from uuid import UUID

from pydantic import BaseModel, ValidationError

from onyx.cache.factory import get_shared_cache_backend

TOKEN_SECONDS = 60


class ExtensionTokenData(BaseModel):
    user_id: UUID
    tenant_id: str


def _token_key(token: str) -> str:
    return f"chrome_browser:token:{token}"


def issue_extension_token(user_id: UUID, tenant_id: str) -> str:
    token = secrets.token_urlsafe(32)
    get_shared_cache_backend().set(
        _token_key(token),
        ExtensionTokenData(user_id=user_id, tenant_id=tenant_id).model_dump_json(),
        ex=TOKEN_SECONDS,
    )
    return token


def redeem_extension_token(token: str) -> ExtensionTokenData | None:
    raw = get_shared_cache_backend().getdel(_token_key(token))
    if raw is None:
        return None
    try:
        return ExtensionTokenData.model_validate_json(raw)
    except ValidationError:
        return None
