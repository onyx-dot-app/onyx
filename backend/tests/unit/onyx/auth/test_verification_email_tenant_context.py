"""Unit tests for tenant binding in UserManager.on_after_request_verify.

The hook serves an unauthenticated request, so it names the workspace itself.
Everything it touches (the user count, the branding the email body is built
from, the audit event) is per-tenant, and the binding is undone even when the
send fails.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from onyx.auth.users import UserManager
from onyx.error_handling.exceptions import OnyxError
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

TENANT_ID = "tenant_0d1c9d5e"


@pytest.mark.asyncio
@patch("onyx.auth.users.emit_audit_event")
@patch("onyx.auth.users.send_user_verification_email")
@patch("onyx.auth.users.get_user_count", new_callable=AsyncMock)
@patch("onyx.auth.users.fetch_ee_implementation_or_noop")
@patch("onyx.auth.users.get_security_settings")
@patch("onyx.auth.users.verify_email_domain")
@patch("onyx.auth.users.EMAIL_CONFIGURED", True)
async def test_on_after_request_verify_binds_address_owner_tenant(
    _mock_verify_domain: MagicMock,
    mock_settings: MagicMock,
    mock_fetch: MagicMock,
    mock_count: AsyncMock,
    mock_send: MagicMock,
    mock_audit: MagicMock,
) -> None:
    mock_settings.return_value = MagicMock(valid_email_domains=[])
    mock_fetch.return_value = lambda _email: TENANT_ID
    seen: list[str | None] = []

    def record(*_args: object, **_kwargs: object) -> int:
        seen.append(CURRENT_TENANT_ID_CONTEXTVAR.get())
        return 1

    mock_count.side_effect = record
    mock_send.side_effect = record
    mock_audit.side_effect = record
    manager = UserManager(MagicMock())

    await manager.on_after_request_verify(
        MagicMock(id="u-1", email="user@example.com"), token="tok", request=None
    )

    assert seen == [TENANT_ID, TENANT_ID, TENANT_ID]
    # Single-tenant resolves through the same call, so pin the noop default.
    mock_fetch.assert_called_once_with(
        "onyx.db.user_tenant_mapping",
        "get_tenant_id_for_email",
        POSTGRES_DEFAULT_SCHEMA,
    )


@pytest.mark.asyncio
@patch("onyx.auth.users.send_user_verification_email")
@patch("onyx.auth.users.get_user_count", new_callable=AsyncMock)
@patch("onyx.auth.users.fetch_ee_implementation_or_noop")
@patch("onyx.auth.users.get_security_settings")
@patch("onyx.auth.users.verify_email_domain")
@patch("onyx.auth.users.EMAIL_CONFIGURED", True)
async def test_on_after_request_verify_resets_tenant_after_send_failure(
    _mock_verify_domain: MagicMock,
    mock_settings: MagicMock,
    mock_fetch: MagicMock,
    mock_count: AsyncMock,
    mock_send: MagicMock,
) -> None:
    mock_settings.return_value = MagicMock(valid_email_domains=[])
    mock_fetch.return_value = lambda _email: TENANT_ID
    mock_count.return_value = 1
    mock_send.side_effect = RuntimeError("smtp down")
    manager = UserManager(MagicMock())
    before: str | None = CURRENT_TENANT_ID_CONTEXTVAR.get()

    with pytest.raises(OnyxError):
        await manager.on_after_request_verify(
            MagicMock(id="u-1", email="user@example.com"), token="tok", request=None
        )

    assert CURRENT_TENANT_ID_CONTEXTVAR.get() == before
