"""Guards the admin OAuth Test endpoint: the admin-only permission gate on the
route, the missing-email rejection, and the snapshot-to-response mapping
(including the not-found shape)."""

import inspect
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from onyx.db.enums import Permission
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.oauth_test import get_oauth_login_claims


def _user(email: str | None) -> MagicMock:
    user = MagicMock()
    user.email = email
    return user


def test_route_is_gated_by_admin_permission_dependency() -> None:
    """The raw claims payload is admin-only. Both the presence of the
    require_permission gate on the route signature and its permission level
    are pinned, so removing or downgrading the gate must fail a test."""
    user_param = inspect.signature(get_oauth_login_claims).parameters["user"]
    dependency = user_param.default.dependency
    assert getattr(dependency, "_is_require_permission", False)
    required = getattr(dependency, "_required_permission", None)
    assert required is Permission.FULL_ADMIN_PANEL_ACCESS


@pytest.mark.asyncio
async def test_missing_email_rejected() -> None:
    with pytest.raises(OnyxError):
        await get_oauth_login_claims(email=None, user=_user(None))


@pytest.mark.asyncio
async def test_not_found_returns_found_false() -> None:
    with patch(
        "onyx.server.manage.oauth_test.get_captured_oauth_claims",
        new=AsyncMock(return_value=None),
    ):
        response = await get_oauth_login_claims(
            email=None, user=_user("admin@example.com")
        )
    assert response.found is False
    assert response.email == "admin@example.com"


@pytest.mark.asyncio
async def test_found_snapshot_maps_to_response() -> None:
    snapshot: dict[str, Any] = {
        "email": "target@example.com",
        "captured_at": "2026-07-01T00:00:00+00:00",
        "oauth_name": "okta",
        "id_token_claims": {"sub": "abc"},
        "userinfo": {"department": "Legal"},
        "directory_profile": None,
        "directory_source": None,
        "token_meta": {"keys": ["access_token"]},
    }
    with (
        patch(
            "onyx.server.manage.oauth_test.get_captured_oauth_claims",
            new=AsyncMock(return_value=snapshot),
        ),
        patch(
            "onyx.server.manage.oauth_test.get_idp_profile_fields",
            return_value={"Department": "Legal"},
        ) as fields_mock,
    ):
        response = await get_oauth_login_claims(
            email="target@example.com", user=_user("admin@example.com")
        )

    fields_mock.assert_called_once_with("target@example.com")

    assert response.found is True
    assert response.email == "target@example.com"
    assert response.captured_at == "2026-07-01T00:00:00+00:00"
    assert response.oauth_name == "okta"
    assert response.directory_profile is None
    assert response.directory_source is None
    assert response.id_token_claims == {"sub": "abc"}
    assert response.userinfo == {"department": "Legal"}
    assert response.resolved_profile == {"Department": "Legal"}
    assert response.token_meta == {"keys": ["access_token"]}
