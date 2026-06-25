"""Unit tests for audit-event emission from the auth seams in UserManager.

Verifies the right AuditAction / outcome / actor is emitted on login success,
login failure, forgot-password, and email-verify, without coupling to the
heavier register/logout flows (their emit calls follow the same one-line
pattern). Emission itself is covered in tests/unit/onyx/utils/test_audit.py.
"""

import json
import logging
from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from fastapi.security import OAuth2PasswordRequestForm

from onyx.auth.users import UserManager


def _audit_events(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    return [
        json.loads(r.getMessage())
        for r in caplog.records
        if r.name.startswith("onyx.audit")
    ]


@pytest.mark.asyncio
@patch("onyx.auth.users.mt_cloud_identify_user")
async def test_on_after_login_emits_login_success(
    _mock_identify: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    user = MagicMock(id="u-1", email="user@example.com")
    manager = UserManager(MagicMock())

    with caplog.at_level(logging.INFO, logger="onyx.audit"):
        await manager.on_after_login(user, request=None, response=None)

    events = _audit_events(caplog)
    assert len(events) == 1
    assert events[0]["action"] == "auth.login"
    assert events[0]["outcome"] == "success"
    assert events[0]["actor"]["email"] == "user@example.com"


@pytest.mark.asyncio
@patch("onyx.auth.users.fetch_ee_implementation_or_noop")
async def test_authenticate_unknown_user_emits_login_failure(
    mock_fetch: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # No tenant mapping -> authenticate() returns None on the unknown-user path.
    mock_fetch.return_value = lambda **_kw: None
    manager = UserManager(MagicMock())
    creds = OAuth2PasswordRequestForm(username="user@example.com", password="wrong")

    with caplog.at_level(logging.INFO, logger="onyx.audit"):
        result = await manager.authenticate(creds)

    assert result is None
    events = _audit_events(caplog)
    assert len(events) == 1
    assert events[0]["action"] == "auth.login_failure"
    assert events[0]["outcome"] == "failure"
    assert events[0]["actor"]["email"] == "user@example.com"


@pytest.mark.asyncio
@patch("onyx.auth.users.send_forgot_password_email")
@patch("onyx.auth.users.fetch_ee_implementation_or_noop")
@patch("onyx.auth.users.EMAIL_CONFIGURED", True)
async def test_on_after_forgot_password_emits_event(
    mock_fetch: MagicMock,
    _mock_send: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_fetch.return_value = AsyncMock(return_value="tenant_1")
    user = MagicMock(id="u-1", email="user@example.com")
    manager = UserManager(MagicMock())

    with caplog.at_level(logging.INFO, logger="onyx.audit"):
        await manager.on_after_forgot_password(user, token="tok", request=None)

    events = _audit_events(caplog)
    assert len(events) == 1
    assert events[0]["action"] == "auth.password_forgot"
    assert events[0]["outcome"] == "success"


@pytest.mark.asyncio
@patch("onyx.auth.users.send_user_verification_email")
@patch("onyx.auth.users.get_user_count", new_callable=AsyncMock)
@patch("onyx.auth.users.get_security_settings")
@patch("onyx.auth.users.verify_email_domain")
async def test_on_after_request_verify_emits_event(
    _mock_verify_domain: MagicMock,
    mock_settings: MagicMock,
    mock_count: AsyncMock,
    _mock_send: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_settings.return_value = MagicMock(valid_email_domains=[])
    mock_count.return_value = 1
    user = MagicMock(id="u-1", email="user@example.com")
    manager = UserManager(MagicMock())

    with caplog.at_level(logging.INFO, logger="onyx.audit"):
        await manager.on_after_request_verify(user, token="tok", request=None)

    events = _audit_events(caplog)
    assert len(events) == 1
    assert events[0]["action"] == "auth.email_verify"
    assert events[0]["outcome"] == "success"


@pytest.mark.asyncio
async def test_on_after_reset_password_emits_event(
    caplog: pytest.LogCaptureFixture,
) -> None:
    user = MagicMock(id="u-1", email="user@example.com")
    manager = UserManager(MagicMock())

    with caplog.at_level(logging.INFO, logger="onyx.audit"):
        await manager.on_after_reset_password(user, request=None)

    events = _audit_events(caplog)
    assert len(events) == 1
    assert events[0]["action"] == "auth.password_reset"
    assert events[0]["outcome"] == "success"
    assert events[0]["actor"]["email"] == "user@example.com"
