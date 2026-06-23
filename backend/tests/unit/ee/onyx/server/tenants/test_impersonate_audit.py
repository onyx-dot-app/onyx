"""Unit tests for audit-event emission from the cloud-superuser impersonate endpoint.

Impersonation is a high-sensitivity access-control action, so both the success
path and the two lookup-failure paths emit an ``auth.impersonate`` event.
Emission plumbing itself is covered in tests/unit/onyx/utils/test_audit.py.
"""

import json
import logging
from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi import Response
from fastapi_users import exceptions

from ee.onyx.server.tenants.admin_api import impersonate_user
from ee.onyx.server.tenants.models import ImpersonateRequest


def _audit_events(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    return [
        json.loads(r.getMessage())
        for r in caplog.records
        if r.name.startswith("onyx.audit")
    ]


def _superuser() -> MagicMock:
    return MagicMock(id="superuser-1", email="root@example.com")


@pytest.mark.asyncio
@patch("ee.onyx.server.tenants.admin_api.auth_backend")
@patch("ee.onyx.server.tenants.admin_api.get_redis_strategy")
@patch("ee.onyx.server.tenants.admin_api.get_user_by_email")
@patch("ee.onyx.server.tenants.admin_api.get_session_with_tenant")
@patch("ee.onyx.server.tenants.admin_api.get_tenant_id_for_email")
async def test_impersonate_success_emits_event(
    mock_tenant_for_email: MagicMock,
    mock_get_session: MagicMock,
    mock_get_user: MagicMock,
    mock_redis_strategy: MagicMock,
    mock_auth_backend: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_tenant_for_email.return_value = "tenant_abc"
    mock_get_session.return_value.__enter__.return_value = MagicMock()
    mock_get_user.return_value = MagicMock(id="target-7", email="target@example.com")
    mock_redis_strategy.return_value.write_token = AsyncMock(return_value="tok")
    mock_auth_backend.transport.get_login_response = AsyncMock(return_value=Response())

    with caplog.at_level(logging.INFO, logger="onyx.audit"):
        await impersonate_user(
            ImpersonateRequest(email="target@example.com"),
            superuser=_superuser(),
        )

    events = _audit_events(caplog)
    assert len(events) == 1
    assert events[0]["action"] == "auth.impersonate"
    assert events[0]["ocsf_class"] == "authentication"
    assert events[0]["outcome"] == "success"
    assert events[0]["resource_type"] == "user"
    assert events[0]["resource_id"] == "target-7"
    assert events[0]["actor"]["email"] == "root@example.com"
    assert events[0]["extra"]["target_email"] == "target@example.com"
    assert events[0]["extra"]["target_tenant_id"] == "tenant_abc"


@pytest.mark.asyncio
@patch("ee.onyx.server.tenants.admin_api.get_tenant_id_for_email")
async def test_impersonate_no_tenant_mapping_emits_failure(
    mock_tenant_for_email: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_tenant_for_email.side_effect = exceptions.UserNotExists()

    with caplog.at_level(logging.INFO, logger="onyx.audit"):
        with pytest.raises(HTTPException):
            await impersonate_user(
                ImpersonateRequest(email="ghost@example.com"),
                superuser=_superuser(),
            )

    events = _audit_events(caplog)
    assert len(events) == 1
    assert events[0]["action"] == "auth.impersonate"
    assert events[0]["outcome"] == "failure"
    assert events[0]["extra"]["target_email"] == "ghost@example.com"


@pytest.mark.asyncio
@patch("ee.onyx.server.tenants.admin_api.get_user_by_email")
@patch("ee.onyx.server.tenants.admin_api.get_session_with_tenant")
@patch("ee.onyx.server.tenants.admin_api.get_tenant_id_for_email")
async def test_impersonate_user_not_in_tenant_emits_failure(
    mock_tenant_for_email: MagicMock,
    mock_get_session: MagicMock,
    mock_get_user: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_tenant_for_email.return_value = "tenant_abc"
    mock_get_session.return_value.__enter__.return_value = MagicMock()
    mock_get_user.return_value = None

    with caplog.at_level(logging.INFO, logger="onyx.audit"):
        with pytest.raises(HTTPException):
            await impersonate_user(
                ImpersonateRequest(email="target@example.com"),
                superuser=_superuser(),
            )

    events = _audit_events(caplog)
    assert len(events) == 1
    assert events[0]["action"] == "auth.impersonate"
    assert events[0]["outcome"] == "failure"
    assert events[0]["extra"]["target_tenant_id"] == "tenant_abc"
