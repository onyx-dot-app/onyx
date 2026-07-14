"""Terminal WebSocket tests (security / handshake authz).

The terminal lives at ``WS /api/build/sessions/{session_id}/terminal`` and
bridges a browser WebSocket to an interactive ``/bin/bash`` PTY inside the
per-user sandbox pod. It uses the same handshake auth dependency as the HTTP
webapp proxy (``_current_webapp_websocket_user``) but an owner-only ownership
check (``_check_terminal_access``) — a shell is owner-only regardless of the
session's sharing scope.

Reaching the actual PTY (the happy path) requires a provisioned sandbox pod
with a live shell, which no session created purely via the HTTP API in this
layer has — that belongs in the Playwright E2E. What we assert here is the
load-bearing security property unique to this route: the WebSocket handshake
is rejected for unauthenticated and non-owner callers *before* any exec into
a pod happens.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

import websockets
from websockets.exceptions import ConnectionClosed
from websockets.exceptions import InvalidStatus

from onyx.db.enums import SharingScope
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.common_utils.test_models import DATestUser


def _terminal_ws_url(session_id: UUID) -> str:
    base = API_SERVER_URL.replace("https://", "wss://").replace("http://", "ws://")
    return f"{base}/build/sessions/{session_id}/terminal"


def _cookie_header(user: DATestUser) -> str | None:
    if not user.cookies:
        return None
    return "; ".join(f"{k}={v}" for k, v in user.cookies.items())


async def _attempt_connect(
    url: str, cookie_header: str | None
) -> tuple[str, int | None]:
    """Try to open the terminal WS. Returns one of:

    - ("rejected", http_status) — handshake denied (dependency/access check)
    - ("closed", close_code)     — accepted then closed by the server
    - ("open", None)             — a usable session was established
    """
    extra_headers = {"Cookie": cookie_header} if cookie_header else None
    try:
        async with websockets.connect(
            url, additional_headers=extra_headers, open_timeout=10
        ) as ws:
            try:
                await asyncio.wait_for(ws.recv(), timeout=2)
                return ("open", None)
            except ConnectionClosed as e:
                return ("closed", _close_code(e))
            except asyncio.TimeoutError:
                return ("open", None)
    except InvalidStatus as e:
        return ("rejected", e.response.status_code)
    except ConnectionClosed as e:
        return ("closed", _close_code(e))


def _close_code(e: ConnectionClosed) -> int | None:
    # `e.code` is deprecated in websockets >= 13; the code lives on `e.rcvd`.
    return e.rcvd.code if e.rcvd is not None else None


def _connect(url: str, cookie_header: str | None) -> tuple[str, int | None]:
    return asyncio.run(_attempt_connect(url, cookie_header))


def test_terminal_ws_requires_auth(admin_user: DATestUser) -> None:
    """No auth cookie → handshake REJECTED (403) before any accept/exec."""
    session_id = UUID(BuildSessionManager.create(admin_user).id)
    BuildSessionManager.set_sharing(admin_user, session_id, SharingScope.PRIVATE)

    outcome, code = _connect(_terminal_ws_url(session_id), cookie_header=None)

    assert outcome == "rejected", (
        f"expected handshake rejection, got {outcome} ({code})"
    )


def test_terminal_ws_blocks_non_owner_on_private(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    """A different authenticated user cannot open a shell into a PRIVATE session."""
    session_id = UUID(BuildSessionManager.create(admin_user).id)
    BuildSessionManager.set_sharing(admin_user, session_id, SharingScope.PRIVATE)

    outcome, code = _connect(
        _terminal_ws_url(session_id), cookie_header=_cookie_header(basic_user)
    )

    assert outcome == "rejected", f"non-owner not rejected, got {outcome} ({code})"


def test_terminal_ws_blocks_non_owner_on_public_org(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    """Even on a PUBLIC_ORG-shared session, a non-owner cannot open a shell.

    The terminal is owner-only regardless of sharing scope (unlike the
    read-only webapp preview, which honors PUBLIC_ORG). Regression guard for
    org members getting shell access into another member's sandbox.
    """
    session_id = UUID(BuildSessionManager.create(admin_user).id)
    BuildSessionManager.set_sharing(admin_user, session_id, SharingScope.PUBLIC_ORG)

    outcome, code = _connect(
        _terminal_ws_url(session_id), cookie_header=_cookie_header(basic_user)
    )

    assert outcome == "rejected", (
        f"non-owner reached PUBLIC_ORG shell ({outcome} {code})"
    )


def test_terminal_ws_blocks_forged_token(admin_user: DATestUser) -> None:
    """A present-but-invalid auth cookie is treated as anonymous and rejected."""
    session_id = UUID(BuildSessionManager.create(admin_user).id)
    BuildSessionManager.set_sharing(admin_user, session_id, SharingScope.PRIVATE)

    outcome, code = _connect(
        _terminal_ws_url(session_id),
        cookie_header="fastapiusersauth=not-a-real-token",
    )

    assert outcome == "rejected", f"forged token not rejected, got {outcome} ({code})"


def test_terminal_ws_owner_handshake_accepted(admin_user: DATestUser) -> None:
    """Positive control: the owner is NOT rejected at the handshake.

    Proves the deny tests above fail because of the authz check — not because
    the route is misrouted/unreachable for everyone. The connection is accepted
    (then the server closes it with 1011 since no real sandbox pod exists in the
    integration layer); the key assertion is that it was never handshake-rejected.
    """
    session_id = UUID(BuildSessionManager.create(admin_user).id)
    BuildSessionManager.set_sharing(admin_user, session_id, SharingScope.PRIVATE)

    outcome, code = _connect(
        _terminal_ws_url(session_id), cookie_header=_cookie_header(admin_user)
    )

    assert outcome != "rejected", f"owner was handshake-rejected (code={code})"
