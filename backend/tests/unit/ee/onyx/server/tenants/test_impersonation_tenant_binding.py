"""The impersonation token must name the impersonated user's workspace.

Session issuance takes an explicit override when the caller has already decided
the workspace. Without one it would fall back to resolving the superuser's own
address, minting a session for the wrong workspace.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from ee.onyx.server.tenants.admin_api import impersonate_user
from shared_configs.contextvars import SESSION_TENANT_OVERRIDE_CONTEXTVAR

_SUPERUSER_TENANT = "tenant_superuser"
_TARGET_TENANT = "tenant_target"


@pytest.mark.asyncio
async def test_token_is_minted_against_the_target_workspace() -> None:
    target_user = SimpleNamespace(id=uuid4(), email="member@target.example")
    superuser = SimpleNamespace(id=uuid4(), email="ops@onyx.app")
    tenant_at_issuance: dict[str, str | None] = {}

    async def capture_write_token(_user: Any) -> str:
        tenant_at_issuance["value"] = SESSION_TENANT_OVERRIDE_CONTEXTVAR.get()
        return "token"

    # A stale override from earlier work on this task must not leak through.
    context_token = SESSION_TENANT_OVERRIDE_CONTEXTVAR.set(_SUPERUSER_TENANT)
    try:
        with (
            patch(
                "ee.onyx.server.tenants.admin_api.get_tenant_id_for_email",
                return_value=_TARGET_TENANT,
            ),
            patch("ee.onyx.server.tenants.admin_api.get_session_with_tenant"),
            patch(
                "ee.onyx.server.tenants.admin_api.get_user_by_email",
                return_value=target_user,
            ),
            patch(
                "ee.onyx.server.tenants.admin_api.get_redis_strategy",
                return_value=SimpleNamespace(write_token=capture_write_token),
            ),
            patch(
                "ee.onyx.server.tenants.admin_api.auth_backend",
                SimpleNamespace(
                    transport=SimpleNamespace(
                        get_login_response=AsyncMock(
                            return_value=SimpleNamespace(set_cookie=lambda **_kw: None)
                        )
                    )
                ),
            ),
            patch("ee.onyx.server.tenants.admin_api.emit_audit_event"),
            patch(
                "ee.onyx.server.tenants.admin_api.actor_from_user", return_value=None
            ),
        ):
            await impersonate_user(
                impersonate_request=SimpleNamespace(email=target_user.email),  # ty: ignore[invalid-argument-type]
                superuser=superuser,  # ty: ignore[invalid-argument-type]
            )
            # Checked before the test's own reset, so this is the handler's
            # restoration and not this fixture's.
            assert SESSION_TENANT_OVERRIDE_CONTEXTVAR.get() == _SUPERUSER_TENANT
    finally:
        SESSION_TENANT_OVERRIDE_CONTEXTVAR.reset(context_token)

    assert tenant_at_issuance["value"] == _TARGET_TENANT
