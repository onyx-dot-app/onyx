"""Webapp proxy tests (security + UX)."""

from __future__ import annotations

from uuid import UUID

import httpx

from onyx.db.enums import SharingScope
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.craft.conftest import SharedSession


def _webapp_url(session_id: UUID, path: str = "") -> str:
    base = f"{API_SERVER_URL}/build/sessions/{session_id}/webapp"
    return f"{base}/{path.lstrip('/')}" if path else base


def _set_scope(user: DATestUser, session_id: UUID, scope: SharingScope) -> None:
    BuildSessionManager.set_sharing(user, session_id, scope)


def _unauth_get(
    session_id: UUID,
    path: str = "",
    follow_redirects: bool = False,
) -> httpx.Response:
    return client.get(
        _webapp_url(session_id, path),
        follow_redirects=follow_redirects,
    )


def _auth_get(
    user: DATestUser,
    session_id: UUID,
    path: str = "",
    follow_redirects: bool = False,
) -> httpx.Response:
    return client.get(
        _webapp_url(session_id, path),
        headers=user.headers,
        cookies=user.cookies,
        follow_redirects=follow_redirects,
    )


def test_proxy_requires_auth_when_private(
    shared_session: SharedSession,
) -> None:
    """Auth-required surfaces as either 401 or a 302 to /auth/login."""
    owner, session_id = shared_session
    _set_scope(owner, session_id, SharingScope.PRIVATE)

    response = _unauth_get(session_id, follow_redirects=False)

    if response.status_code == 302:
        assert "/auth/login" in response.headers.get("location", "")
    else:
        assert response.status_code == 401


def test_proxy_rejects_forged_auth_cookie(
    shared_session: SharedSession,
) -> None:
    """A forged cookie resolves to no user; public_org still requires auth."""
    owner, session_id = shared_session
    _set_scope(owner, session_id, SharingScope.PUBLIC_ORG)

    response = client.get(
        _webapp_url(session_id),
        cookies={"fastapiusersauth": "not-a-real-token"},
        follow_redirects=False,
    )

    if response.status_code == 302:
        assert "/auth/login" in response.headers.get("location", "")
    else:
        assert response.status_code == 401


def test_proxy_no_webapp_port_renders_branded_offline_page(
    shared_session: SharedSession,
) -> None:
    # shared_session is headless, so no Next.js port is allocated.
    owner, session_id = shared_session

    response = _auth_get(owner, session_id, follow_redirects=False)

    # No Next.js port -> _offline_html_response, which is always 503.
    assert response.status_code == 503
    assert "text/html" in response.headers.get("content-type", "").lower()
    body = response.text
    assert "Craft" in body
    assert "crafting_table" in body


def test_webapp_download_route_not_shadowed_by_catchall(
    admin_user: DATestUser,
) -> None:
    """``/webapp-download`` resolves to the zip endpoint, not the catch-all proxy."""
    session_id = BuildSessionManager.create(admin_user).id

    response = client.get(
        f"{API_SERVER_URL}/build/sessions/{session_id}/webapp-download",
        headers=admin_user.headers,
        cookies=admin_user.cookies,
        follow_redirects=False,
    )

    content_type = response.headers.get("content-type", "").lower()
    assert "text/html" not in content_type, (
        "webapp-download was shadowed by the catch-all proxy route"
    )
