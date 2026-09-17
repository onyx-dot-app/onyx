"""Canvas OAuth2 helpers shared by the Canvas connector and the LTI API.

Canvas issues one-hour access tokens via the standard authorization-code
grant. The refresh token does not rotate and does not expire on its own; it
dies only if the user revokes it, the user is deleted, or the developer key is
turned off. See https://developerdocs.instructure.com/services/canvas/oauth2.

Token state lives inside ``Credential.credential_json`` next to the legacy
``canvas_access_token`` key so every existing reader (connector, EE enrollment
sync, LTI API) keeps working unchanged. A credential without
``canvas_refresh_token`` is a legacy pasted personal access token and is
treated as static.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode

import requests
from pydantic import BaseModel

from onyx.utils.logger import setup_logger

logger = setup_logger()

# Credential JSON keys. ``CANVAS_ACCESS_TOKEN_KEY`` predates OAuth support and
# must stay stable for backwards compatibility with pasted tokens.
CANVAS_ACCESS_TOKEN_KEY = "canvas_access_token"
CANVAS_REFRESH_TOKEN_KEY = "canvas_refresh_token"
CANVAS_TOKEN_EXPIRES_AT_KEY = "canvas_token_expires_at"
CANVAS_USER_ID_KEY = "canvas_user_id"
CANVAS_USER_NAME_KEY = "canvas_user_name"
CANVAS_BASE_URL_KEY = "canvas_base_url"
CANVAS_OAUTH_CLIENT_ID_KEY = "canvas_oauth_client_id"
# Set (epoch seconds) when Canvas permanently rejected the refresh token, so
# status endpoints can report "expired" without a network call.
CANVAS_TOKEN_INVALID_AT_KEY = "canvas_token_invalid_at"

# Refresh when fewer than this many seconds remain on the access token.
CANVAS_TOKEN_REFRESH_MARGIN_SECONDS = 5 * 60
_CANVAS_OAUTH_TIMEOUT_SECONDS = 30
_CANVAS_DEFAULT_EXPIRES_IN_SECONDS = 3600

# Every Canvas REST endpoint Onyx calls with an instructor token, in Canvas's
# ``url:<VERB>|<route>`` scope format. Admins paste this list into the API
# developer key when enabling "Enforce Scopes". Verified against
# ``TokenScopes.all_scopes`` in Canvas: ``users/self`` is covered by
# ``users/:id`` and ``courses/{id}`` by ``courses/:id``.
CANVAS_OAUTH_REQUIRED_SCOPES: list[str] = [
    "url:GET|/api/v1/users/:id",
    "url:GET|/api/v1/courses",
    "url:GET|/api/v1/courses/:id",
    "url:GET|/api/v1/courses/:course_id/pages",
    "url:GET|/api/v1/courses/:course_id/assignments",
    "url:GET|/api/v1/announcements",
    "url:GET|/api/v1/courses/:course_id/files",
    "url:GET|/api/v1/courses/:course_id/modules",
    "url:GET|/api/v1/courses/:course_id/modules/:module_id/items",
    "url:GET|/api/v1/courses/:course_id/quizzes",
    "url:GET|/api/v1/courses/:course_id/discussion_topics",
    "url:GET|/api/v1/courses/:course_id/enrollments",
]

# Canvas token-endpoint error codes that mean the refresh token is dead and
# retrying will never help.
_PERMANENT_TOKEN_ERRORS = {"invalid_grant", "invalid_client", "unauthorized_client"}


class CanvasOAuthError(Exception):
    """Raised when the Canvas token endpoint rejects a request.

    ``permanent`` is True when the grant itself is invalid (revoked refresh
    token, deleted user, developer key turned off) and the instructor must
    reconnect. Transient failures (network, 5xx) leave it False.
    """

    def __init__(
        self,
        message: str,
        *,
        error_code: str | None = None,
        permanent: bool = False,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.permanent = permanent


class CanvasOAuthTokens(BaseModel):
    access_token: str
    refresh_token: str | None = None
    expires_in: int = _CANVAS_DEFAULT_EXPIRES_IN_SECONDS
    canvas_user_id: int | None = None
    canvas_user_name: str | None = None

    @classmethod
    def from_token_response(cls, payload: Mapping[str, Any]) -> "CanvasOAuthTokens":
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise CanvasOAuthError(
                "Canvas token response did not include an access token"
            )

        refresh_token = payload.get("refresh_token")
        expires_in = payload.get("expires_in")
        user = payload.get("user")
        user_id: int | None = None
        user_name: str | None = None
        if isinstance(user, Mapping):
            raw_user_id = user.get("id")
            if isinstance(raw_user_id, int):
                user_id = raw_user_id
            elif isinstance(raw_user_id, str) and raw_user_id.isdigit():
                user_id = int(raw_user_id)
            raw_user_name = user.get("name")
            if isinstance(raw_user_name, str) and raw_user_name:
                user_name = raw_user_name

        return cls(
            access_token=access_token,
            refresh_token=refresh_token if isinstance(refresh_token, str) else None,
            expires_in=(
                expires_in
                if isinstance(expires_in, int) and expires_in > 0
                else _CANVAS_DEFAULT_EXPIRES_IN_SECONDS
            ),
            canvas_user_id=user_id,
            canvas_user_name=user_name,
        )


def _oauth_base_url(canvas_base_url: str) -> str:
    return canvas_base_url.rstrip("/").removesuffix("/api/v1")


def canvas_oauth_authorize_url(canvas_base_url: str) -> str:
    return f"{_oauth_base_url(canvas_base_url)}/login/oauth2/auth"


def canvas_oauth_token_url(canvas_base_url: str) -> str:
    return f"{_oauth_base_url(canvas_base_url)}/login/oauth2/token"


def build_canvas_authorize_url(
    *,
    canvas_base_url: str,
    client_id: str,
    redirect_uri: str,
    state: str,
    scopes: list[str] | None = None,
    purpose: str | None = None,
) -> str:
    params: dict[str, str] = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
    }
    if scopes:
        params["scope"] = " ".join(scopes)
    if purpose:
        params["purpose"] = purpose
    return f"{canvas_oauth_authorize_url(canvas_base_url)}?{urlencode(params)}"


def _post_token_request(
    canvas_base_url: str, data: dict[str, str]
) -> CanvasOAuthTokens:
    try:
        response = requests.post(
            canvas_oauth_token_url(canvas_base_url),
            data=data,
            timeout=_CANVAS_OAUTH_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        raise CanvasOAuthError(f"Could not reach the Canvas token endpoint: {e}") from e

    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    if response.status_code >= 400:
        error_code = payload.get("error")
        error_code = error_code if isinstance(error_code, str) else None
        description = payload.get("error_description")
        message = (
            description
            if isinstance(description, str) and description
            else error_code
            or f"Canvas token endpoint returned HTTP {response.status_code}"
        )
        permanent = response.status_code < 500 and (
            error_code in _PERMANENT_TOKEN_ERRORS or response.status_code in (400, 401)
        )
        raise CanvasOAuthError(message, error_code=error_code, permanent=permanent)

    return CanvasOAuthTokens.from_token_response(payload)


def exchange_canvas_authorization_code(
    *,
    canvas_base_url: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
) -> CanvasOAuthTokens:
    return _post_token_request(
        canvas_base_url,
        {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        },
    )


def refresh_canvas_access_token(
    *,
    canvas_base_url: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> CanvasOAuthTokens:
    return _post_token_request(
        canvas_base_url,
        {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        },
    )


def revoke_canvas_access_token(*, canvas_base_url: str, access_token: str) -> bool:
    """Best-effort revocation at Canvas. Returns True if Canvas accepted it."""
    try:
        response = requests.delete(
            canvas_oauth_token_url(canvas_base_url),
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=_CANVAS_OAUTH_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        logger.warning("Failed to revoke Canvas access token: %s", e)
        return False
    if response.status_code >= 400:
        logger.warning(
            "Canvas rejected token revocation (status=%d)", response.status_code
        )
        return False
    return True


def credential_json_from_tokens(
    tokens: CanvasOAuthTokens,
    *,
    canvas_base_url: str,
    client_id: str,
    existing: Mapping[str, Any] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Merge a token response into a credential JSON blob.

    Keeps unrelated keys (e.g. ``respect_release_dates``) and the existing
    refresh token when Canvas omits one (refresh responses never include it).
    """
    current_time = time.time() if now is None else now
    credential_json: dict[str, Any] = dict(existing or {})
    credential_json[CANVAS_ACCESS_TOKEN_KEY] = tokens.access_token
    credential_json[CANVAS_TOKEN_EXPIRES_AT_KEY] = int(current_time + tokens.expires_in)
    credential_json[CANVAS_BASE_URL_KEY] = _oauth_base_url(canvas_base_url)
    credential_json[CANVAS_OAUTH_CLIENT_ID_KEY] = client_id
    if tokens.refresh_token:
        credential_json[CANVAS_REFRESH_TOKEN_KEY] = tokens.refresh_token
    if tokens.canvas_user_id is not None:
        credential_json[CANVAS_USER_ID_KEY] = tokens.canvas_user_id
    if tokens.canvas_user_name:
        credential_json[CANVAS_USER_NAME_KEY] = tokens.canvas_user_name
    credential_json.pop(CANVAS_TOKEN_INVALID_AT_KEY, None)
    return credential_json


def canvas_credential_is_oauth(credential_json: Mapping[str, Any] | None) -> bool:
    if not credential_json:
        return False
    return bool(credential_json.get(CANVAS_REFRESH_TOKEN_KEY))


def canvas_credential_is_invalidated(
    credential_json: Mapping[str, Any] | None,
) -> bool:
    if not credential_json:
        return False
    return credential_json.get(CANVAS_TOKEN_INVALID_AT_KEY) is not None


def canvas_token_needs_refresh(
    credential_json: Mapping[str, Any],
    *,
    now: float | None = None,
    margin_seconds: int = CANVAS_TOKEN_REFRESH_MARGIN_SECONDS,
) -> bool:
    """True when an OAuth credential's access token is missing or near expiry."""
    if not canvas_credential_is_oauth(credential_json):
        return False
    if not credential_json.get(CANVAS_ACCESS_TOKEN_KEY):
        return True
    expires_at = credential_json.get(CANVAS_TOKEN_EXPIRES_AT_KEY)
    if not isinstance(expires_at, (int, float)):
        # Unknown expiry: refresh so we learn it.
        return True
    current_time = time.time() if now is None else now
    return current_time >= float(expires_at) - margin_seconds


def mark_canvas_credential_invalid(
    credential_json: Mapping[str, Any], *, now: float | None = None
) -> dict[str, Any]:
    updated = dict(credential_json)
    updated[CANVAS_TOKEN_INVALID_AT_KEY] = int(time.time() if now is None else now)
    return updated


def refresh_canvas_credential_json(
    credential_json: Mapping[str, Any],
    *,
    client_id: str,
    client_secret: str,
    canvas_base_url: str | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Exchange the stored refresh token for a fresh access token.

    Raises ``CanvasOAuthError`` (``permanent=True`` when the instructor must
    reconnect). Callers decide how to persist the returned JSON.
    """
    refresh_token = credential_json.get(CANVAS_REFRESH_TOKEN_KEY)
    if not isinstance(refresh_token, str) or not refresh_token:
        raise CanvasOAuthError("Canvas credential has no refresh token", permanent=True)
    base_url = canvas_base_url or credential_json.get(CANVAS_BASE_URL_KEY)
    if not isinstance(base_url, str) or not base_url:
        raise CanvasOAuthError(
            "Canvas credential does not record which Canvas instance issued it",
            permanent=True,
        )

    tokens = refresh_canvas_access_token(
        canvas_base_url=base_url,
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
    )
    return credential_json_from_tokens(
        tokens,
        canvas_base_url=base_url,
        client_id=client_id,
        existing=credential_json,
        now=now,
    )


def refresh_canvas_credential_json_if_needed(
    credential_json: Mapping[str, Any],
    *,
    client_id: str | None,
    client_secret: str | None,
    canvas_base_url: str | None = None,
    force: bool = False,
    now: float | None = None,
) -> tuple[dict[str, Any], bool]:
    """Return ``(credential_json, refreshed)``.

    Static (pasted token) credentials are returned untouched. OAuth
    credentials are refreshed when near expiry (or ``force``). If the OAuth
    client is not configured on this instance we log and return the current
    tokens rather than failing, so a still-valid access token keeps working.
    """
    if not canvas_credential_is_oauth(credential_json):
        return dict(credential_json), False
    if not force and not canvas_token_needs_refresh(credential_json, now=now):
        return dict(credential_json), False
    if not client_id or not client_secret:
        logger.warning(
            "Canvas OAuth credential needs a refresh but LTI_CANVAS_OAUTH_CLIENT_ID/"
            "SECRET are not configured; using the current access token as-is"
        )
        return dict(credential_json), False

    return (
        refresh_canvas_credential_json(
            credential_json,
            client_id=client_id,
            client_secret=client_secret,
            canvas_base_url=canvas_base_url,
            now=now,
        ),
        True,
    )
