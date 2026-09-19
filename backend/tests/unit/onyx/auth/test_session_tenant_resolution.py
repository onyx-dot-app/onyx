"""Which workspace a freshly issued session names.

Only a caller that has already decided the workspace may set it. The request's
own tenant context is whatever cookie the browser sent, which on a re-login can
name a workspace the user being authenticated does not belong to, so reading it
here would hand them a session for someone else's.
"""

from typing import Any
from unittest.mock import patch

import pytest

from onyx.auth.users import resolve_tenant_for_user
from shared_configs.contextvars import (
    CURRENT_TENANT_ID_CONTEXTVAR,
    SESSION_TENANT_OVERRIDE_CONTEXTVAR,
)

_COOKIE_TENANT = "tenant_from_stale_cookie"
_MEMBER_TENANT = "tenant_the_user_belongs_to"
_PINNED_TENANT = "tenant_pinned_by_sso"


def _catalog_returns(tenant_id: str) -> Any:
    async def _resolve(**_kwargs: Any) -> str:
        return tenant_id

    return lambda *_args, **_kwargs: _resolve


@pytest.mark.asyncio
async def test_ambient_request_tenant_does_not_decide_the_session() -> None:
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(_COOKIE_TENANT)
    try:
        with patch(
            "onyx.auth.users.fetch_ee_implementation_or_noop",
            _catalog_returns(_MEMBER_TENANT),
        ):
            resolved = await resolve_tenant_for_user("member@example.com")
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    assert resolved == _MEMBER_TENANT


@pytest.mark.asyncio
async def test_explicit_override_wins_over_the_catalog() -> None:
    """An SSO login pins its workspace before the user row exists, so the
    catalog cannot answer for a first-time member."""
    token = SESSION_TENANT_OVERRIDE_CONTEXTVAR.set(_PINNED_TENANT)
    try:
        with patch(
            "onyx.auth.users.fetch_ee_implementation_or_noop",
            _catalog_returns(_MEMBER_TENANT),
        ):
            resolved = await resolve_tenant_for_user("newcomer@example.com")
    finally:
        SESSION_TENANT_OVERRIDE_CONTEXTVAR.reset(token)

    assert resolved == _PINNED_TENANT
