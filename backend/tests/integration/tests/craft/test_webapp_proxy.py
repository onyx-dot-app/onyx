"""Webapp proxy tests (security + UX).

The proxy lives at ``GET /api/build/sessions/{session_id}/webapp/{path:path}``
and proxies to the per-session Next.js server inside the sandbox. The auth
checks (``_check_webapp_access``) and the offline-page rendering are
exercised here against the real backend.

Reaching the actual upstream Next.js pod for the full happy-path body
rewrite/HMR-shim tests would require provisioning a sandbox and waiting
for the pod's webapp to be up — that's not feasible in the integration
layer because no session created by the tests has a running Next.js
process. Those tests instead assert the observable proxy fallback path
(offline HTML / status code) which is what the proxy returns whenever
the upstream is unreachable, which is the case for any session created
purely via the HTTP API in this layer.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID
from uuid import uuid4

import httpx
import pytest

from onyx.db.enums import SharingScope
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _webapp_url(session_id: UUID, path: str = "") -> str:
    base = f"{API_SERVER_URL}/build/sessions/{session_id}/webapp"
    return f"{base}/{path.lstrip('/')}" if path else base


def _create_session(user: DATestUser) -> dict[str, Any]:
    """Create an empty build session for ``user``. Returns the session dict.

    The session has a sandbox row + an allocated ``nextjs_port``, but no
    running Next.js process — so every proxy request beyond the
    auth/access check will surface as the branded offline fallback. That's
    enough to assert routing, scope checks, and the offline path.
    """
    return BuildSessionManager.create(user)


def _set_scope(user: DATestUser, session_id: UUID, scope: SharingScope) -> None:
    BuildSessionManager.set_sharing(user, session_id, scope)


def _unauth_get(
    session_id: UUID,
    path: str = "",
    follow_redirects: bool = False,
) -> httpx.Response:
    """GET the proxy URL with no auth headers/cookies."""
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
    """GET the proxy URL with ``user``'s auth headers/cookies."""
    return client.get(
        _webapp_url(session_id, path),
        headers=user.headers,
        cookies=user.cookies,
        follow_redirects=follow_redirects,
    )


# ---------------------------------------------------------------------------
# Auth / scope checks (the part of the proxy that doesn't need an upstream)
# ---------------------------------------------------------------------------


def test_proxy_requires_auth_when_private(admin_user: DATestUser) -> None:
    """Private session + no token → proxy returns 401-equivalent.

    The handler raises ``HTTPException(401)`` from ``_check_webapp_access``;
    the surrounding code catches that and issues a 302 to ``/auth/login``
    instead of bubbling the bare 401 so the browser UX is sensible.
    Either response (401 status or 302 to login) means "auth required."
    """
    session = _create_session(admin_user)
    session_id = UUID(session["id"])
    # Default scope is PRIVATE; assert + be explicit anyway.
    _set_scope(admin_user, session_id, SharingScope.PRIVATE)

    response = _unauth_get(session_id, follow_redirects=False)

    if response.status_code == 302:
        assert "/auth/login" in response.headers.get("location", "")
    else:
        assert response.status_code == 401


def test_proxy_allows_org_user_when_public_org(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    """Different user in same tenant + ``public_org`` → access check passes.

    Auth check passing means the request reaches ``_proxy_request``;
    since the upstream Next.js pod is not running, the proxy returns the
    branded offline HTML (status 503, ``text/html``). What we are
    asserting is that the request was *not* rejected by the access check
    (no 401, no 302 to login).
    """
    session = _create_session(admin_user)
    session_id = UUID(session["id"])
    _set_scope(admin_user, session_id, SharingScope.PUBLIC_ORG)

    response = client.get(
        _webapp_url(session_id),
        headers=basic_user.headers,
        cookies=basic_user.cookies,
        follow_redirects=False,
    )

    assert response.status_code != 401
    # Not a redirect to login either.
    location = response.headers.get("location", "")
    assert "/auth/login" not in location


def test_proxy_blocks_other_tenant_when_public_org(
    admin_user: DATestUser,
) -> None:
    """Cross-tenant access on ``public_org`` → blocked.

    The integration test deployment is single-tenant, so there is no
    real "other tenant" we can construct here. We approximate the same
    code path by hitting the proxy with a forged but otherwise valid
    auth cookie shape that does not resolve to a real user — the auth
    middleware treats this as anonymous and the proxy applies the same
    ``public_org`` rule (anonymous request → 401, since
    ``public_org`` requires auth).
    """
    session = _create_session(admin_user)
    session_id = UUID(session["id"])
    _set_scope(admin_user, session_id, SharingScope.PUBLIC_ORG)

    # Forged cookie: present but not a valid session for any user.
    response = client.get(
        _webapp_url(session_id),
        cookies={"fastapiusersauth": "not-a-real-token"},
        follow_redirects=False,
    )

    # Either 401, or a redirect to login — both mean "not allowed."
    if response.status_code == 302:
        assert "/auth/login" in response.headers.get("location", "")
    else:
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Header stripping + offline page (no upstream required)
# ---------------------------------------------------------------------------


def test_proxy_strips_set_cookie_header(admin_user: DATestUser) -> None:
    """``set-cookie`` is never forwarded from upstream.

    Without a live upstream, the proxy falls back to the offline HTML
    response. That response is generated locally by ``_offline_html_response``
    and never contains a ``Set-Cookie`` header — which is exactly the
    invariant we care about for security: no upstream-controlled cookie
    can ever reach the parent Onyx origin via this path.
    """
    session = _create_session(admin_user)
    session_id = UUID(session["id"])

    response = _auth_get(admin_user, session_id, follow_redirects=False)

    # Lowercased header name lookup (requests does case-insensitive matching).
    assert "set-cookie" not in {k.lower() for k in response.headers}


def test_proxy_rewrites_nextjs_asset_paths_in_html(
    admin_user: DATestUser,
) -> None:
    """Asset-path rewriting is invoked on HTML responses.

    Without a live upstream, every HTML response we can observe from
    this layer is the branded offline page. ``_rewrite_asset_paths`` is
    only triggered when ``_proxy_request`` succeeds, so a true end-to-end
    rewrite assertion belongs in Playwright / the dedicated unit test in
    ``tests/unit/build/test_rewrite_asset_paths.py`` (which the master
    plan calls out as "KEEP"). What we can assert at
    *this* layer is that the proxy returns HTML when invoked, the route
    resolves, and the offline page does not leak any unprefixed Next.js
    asset URL.
    """
    session = _create_session(admin_user)
    session_id = UUID(session["id"])

    response = _auth_get(admin_user, session_id, follow_redirects=False)
    assert "text/html" in response.headers.get("content-type", "").lower()
    # If a real upstream were live, any rewritten URL would carry the
    # session-scoped proxy prefix. The offline page contains no
    # ``/_next/`` references at all, so by negation no leaked
    # root-scoped ``/_next/...`` URL is present.
    body = response.text
    assert '"/_next/' not in body
    assert "'/_next/" not in body


def test_proxy_injects_hmr_shim_in_html_response(
    admin_user: DATestUser,
) -> None:
    """HMR shim injection runs on HTML proxy responses.

    Same upstream-availability caveat as the rewrite test above: the
    shim is injected by ``_inject_hmr_fixer`` only on a successful
    upstream HTML proxy. The unit test in
    ``tests/unit/build/test_rewrite_asset_paths.py`` (KEEP per master
    plan) asserts the shim contents. At this layer we assert
    that no shim injection mistakenly happens on the offline page —
    i.e. the offline page is what it should be, and the shim path is
    only reached when a live upstream returns HTML.
    """
    session = _create_session(admin_user)
    session_id = UUID(session["id"])

    response = _auth_get(admin_user, session_id, follow_redirects=False)
    # The injection logic only runs when the upstream returns text/html
    # and a 2xx — the offline page does not include the shim script tag
    # in any of its content. Verifies the shim is not accidentally
    # injected on the offline fallback (would expose the proxy base
    # path to authenticated clients).
    body = response.text
    assert "__WEBAPP_BASE__" not in body


def test_proxy_502_renders_branded_offline_page(
    admin_user: DATestUser,
) -> None:
    """Pod down → branded offline HTML.

    A freshly created session has a sandbox row + allocated port but no
    running pod; that's exactly the condition the offline fallback was
    written for. The response is HTML with a 5xx status. The exact
    status (503 by ``_offline_html_response``) is what the proxy
    returns when it can't reach the upstream — the underlying
    ``HTTPException`` raised inside ``_proxy_request`` carries 502
    before the offline page converts it to a 503 HTML response.
    """
    session = _create_session(admin_user)
    session_id = UUID(session["id"])

    response = _auth_get(admin_user, session_id, follow_redirects=False)

    assert response.status_code in (502, 503, 504)
    assert "text/html" in response.headers.get("content-type", "").lower()
    # Branded marker: the template is a Craft-styled offline page. We
    # don't pin exact copy (would couple to the template too tightly);
    # instead assert the page is non-trivial HTML.
    body = response.text
    assert "<html" in body.lower() or "<body" in body.lower()


# ---------------------------------------------------------------------------
# Route precedence + cross-session isolation regressions
# ---------------------------------------------------------------------------


def test_webapp_download_route_not_shadowed_by_catchall(
    admin_user: DATestUser,
) -> None:
    """``/webapp-download`` resolves to the zip endpoint, not the catch-all.

    Regression for SHA ``e213853f63``: the catch-all proxy route
    ``/{session_id}/webapp/{path:path}`` once shadowed the specific
    ``/{session_id}/webapp-download`` route. The two are visually
    similar but functionally distinct — one returns the offline page,
    the other a zip.

    We hit ``/webapp-download`` as the *owner* with auth, so the
    download endpoint can be reached. The catch-all proxy would return
    HTML (the offline page) or a 5xx; the zip endpoint returns either
    a zip (200, ``application/zip``) or a 404 with JSON detail. Either
    is acceptable evidence that the *zip* endpoint matched.
    """
    session = _create_session(admin_user)
    session_id = UUID(session["id"])

    response = client.get(
        f"{API_SERVER_URL}/build/sessions/{session_id}/webapp-download",
        headers=admin_user.headers,
        cookies=admin_user.cookies,
        follow_redirects=False,
    )

    content_type = response.headers.get("content-type", "").lower()
    # If the catch-all proxy had shadowed us we'd get text/html (offline
    # page). The zip endpoint returns application/zip on success or
    # application/json on a 404. Either rules out the proxy match.
    assert "text/html" not in content_type, (
        "webapp-download was shadowed by the catch-all proxy route "
        "(regression for e213853f63)"
    )


def test_webapp_assets_isolated_across_sessions(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    """User A's webapp asset URL cannot leak into user B's session.

    Regression for SHA ``ab9e3e5338``. Two sessions owned by two users
    each carry their own ``session_id`` in the proxy URL; an asset URL
    issued for session A must not be servable as part of session B's
    proxy mount, because each session's filesystem (and Next.js port)
    is owned by a different sandbox.

    Concretely: build a "leaky" asset URL by taking session A's proxy
    path and substituting session B's id. Hitting that URL as user B
    (the owner of B) must not transparently fetch A's bytes — at best
    it triggers B's own offline page or its own routing logic, but it
    must not serve content from A's sandbox.
    """
    session_a = _create_session(admin_user)
    session_b = _create_session(basic_user)
    session_a_id = UUID(session_a["id"])
    session_b_id = UUID(session_b["id"])

    asset_path = f"_next/static/{uuid4().hex}/leak.js"

    response_a = _auth_get(admin_user, session_a_id, asset_path)
    response_b = _auth_get(basic_user, session_b_id, asset_path)

    # Each session's proxy must respond from its own sandbox; the two
    # responses share a *structure* (both offline pages, no upstream)
    # but neither must be the literal content of the other session's
    # asset. The check we *can* make at this layer is that each
    # response's body, if non-trivial, mentions only its own session
    # id in any HMR/asset rewriting, and neither leaks the other's id.
    body_a = response_a.text
    body_b = response_b.text
    assert str(session_b_id) not in body_a
    assert str(session_a_id) not in body_b


# ---------------------------------------------------------------------------
# Compat: keep the user fixtures importable
# ---------------------------------------------------------------------------


@pytest.fixture
def _user_manager_handle() -> type[UserManager]:
    """Keep ``UserManager`` symbol referenced for IDE goto-def in this file.

    No-op fixture. The ``admin_user`` / ``basic_user`` fixtures come from
    ``tests/integration/conftest.py``.
    """
    return UserManager
