"""OAuth provider configuration registry.

Each entry describes one provider's OAuth quirks (authorize URL,
token URL, scope, scope param name, extra authorize params, and
response parsers for both the initial grant and the refresh-token
exchange). Owned by `external_apps/` rather than the API route module
so non-API callers (the db-side `refresh_credentials` helper) can
read it without creating a layering loop.
"""

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from typing import Any

from onyx.db.models import ExternalApp
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


@dataclass(frozen=True)
class OAuthProvider:
    """Provider-specific OAuth details. Resolved by `app.name`."""

    app_name: str
    authorize_url: str
    token_url: str
    scope: str
    # Most providers use `scope=`; Slack uses `user_scope=` to request
    # tokens that act as the user rather than as a bot.
    scope_param: str
    # Extra static query-string params on the authorize URL (e.g.
    # Google's `access_type=offline&prompt=consent` to get refresh
    # tokens, `response_type=code` where required, etc.).
    extra_authorize_params: dict[str, str] = field(default_factory=dict)
    # Parser for the initial-grant token response. Receives the JSON
    # response body and returns the dict to persist in
    # `user_credentials`.
    extract_credentials: Callable[[dict[str, Any]], dict[str, Any]] = lambda _body: {}
    # Parser for the refresh-token response. Slack reshapes the
    # response between initial grant (nested under `authed_user`) and
    # refresh (flat) — so the two parsers diverge. Returns only the
    # fields that should be updated; caller preserves anything not
    # explicitly returned (team_id, authed_user_id, etc.).
    extract_refresh_credentials: Callable[[dict[str, Any]], dict[str, Any]] = (
        lambda _body: {}
    )


# ── Parsers: initial grant ──────────────────────────────────────────


def _slack_extract_credentials(response_data: dict[str, Any]) -> dict[str, Any]:
    """Slack v2 with `user_scope` puts the user token under
    `authed_user.access_token`. Top-level `access_token` would be the
    bot token, which we don't request.
    """
    authed_user = response_data.get("authed_user") or {}
    access_token = authed_user.get("access_token")
    if not access_token:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            "Slack OAuth response did not contain a user access token. "
            "Make sure the Slack app has user token scopes configured.",
        )
    creds: dict[str, Any] = {
        "access_token": access_token,
        "team_id": (response_data.get("team") or {}).get("id"),
        "team_name": (response_data.get("team") or {}).get("name"),
        "authed_user_id": authed_user.get("id"),
        "scope": authed_user.get("scope"),
    }
    if authed_user.get("refresh_token"):
        creds["refresh_token"] = authed_user["refresh_token"]
    if authed_user.get("expires_in"):
        creds["expires_in"] = authed_user["expires_in"]
    return creds


def _google_extract_credentials(response_data: dict[str, Any]) -> dict[str, Any]:
    """Google's OAuth 2.0 response is flat (standards-compliant)."""
    access_token = response_data.get("access_token")
    if not access_token:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            "Google OAuth response did not contain an access token.",
        )
    creds: dict[str, Any] = {
        "access_token": access_token,
        "scope": response_data.get("scope"),
        "token_type": response_data.get("token_type"),
    }
    if response_data.get("refresh_token"):
        creds["refresh_token"] = response_data["refresh_token"]
    if response_data.get("expires_in"):
        creds["expires_in"] = response_data["expires_in"]
    if response_data.get("id_token"):
        creds["id_token"] = response_data["id_token"]
    return creds


def _linear_extract_credentials(response_data: dict[str, Any]) -> dict[str, Any]:
    """Linear's response is also flat, like Google."""
    access_token = response_data.get("access_token")
    if not access_token:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            "Linear OAuth response did not contain an access token.",
        )
    creds: dict[str, Any] = {
        "access_token": access_token,
        "scope": response_data.get("scope"),
        "token_type": response_data.get("token_type"),
    }
    if response_data.get("refresh_token"):
        creds["refresh_token"] = response_data["refresh_token"]
    if response_data.get("expires_in"):
        creds["expires_in"] = response_data["expires_in"]
    return creds


# ── Parsers: refresh ────────────────────────────────────────────────


def _flat_refresh_extract(response_data: dict[str, Any]) -> dict[str, Any]:
    """Standard OAuth 2.0 refresh-token response shape — tokens at the
    top level. Returns only the fields that should be updated;
    `refresh_credentials` merges over existing user_credentials so
    fields not present here (team_id, authed_user_id, etc.) survive.

    Slack's refresh response also follows this shape — only its
    initial-grant response is nested under `authed_user`.
    """
    creds: dict[str, Any] = {}
    if response_data.get("access_token"):
        creds["access_token"] = response_data["access_token"]
    if response_data.get("expires_in"):
        creds["expires_in"] = response_data["expires_in"]
    # Rotation: if the provider returned a new refresh_token, use it.
    # If not (Google's standard behavior — refresh tokens don't
    # rotate), the merge in `refresh_credentials` preserves the old.
    if response_data.get("refresh_token"):
        creds["refresh_token"] = response_data["refresh_token"]
    if response_data.get("scope"):
        creds["scope"] = response_data["scope"]
    return creds


# ── Provider entries ────────────────────────────────────────────────


SLACK_PROVIDER = OAuthProvider(
    app_name="Slack",
    authorize_url="https://slack.com/oauth/v2/authorize",
    token_url="https://slack.com/api/oauth.v2.access",
    scope=",".join(
        [
            "chat:write",
            "channels:history",
            "channels:read",
            "groups:history",
            "groups:read",
            "im:history",
            "im:read",
            "users:read",
        ]
    ),
    scope_param="user_scope",
    extra_authorize_params={},
    extract_credentials=_slack_extract_credentials,
    extract_refresh_credentials=_flat_refresh_extract,
)


GOOGLE_CALENDAR_PROVIDER = OAuthProvider(
    app_name="Google Calendar",
    authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
    token_url="https://oauth2.googleapis.com/token",
    scope="https://www.googleapis.com/auth/calendar",
    scope_param="scope",
    extra_authorize_params={
        "response_type": "code",
        # access_type=offline gets a refresh_token; prompt=consent
        # forces fresh consent so refresh_token is reliably issued
        # (Google omits it on silent re-auth otherwise).
        "access_type": "offline",
        "prompt": "consent",
    },
    extract_credentials=_google_extract_credentials,
    extract_refresh_credentials=_flat_refresh_extract,
)


LINEAR_PROVIDER = OAuthProvider(
    app_name="Linear",
    authorize_url="https://linear.app/oauth/authorize",
    token_url="https://api.linear.app/oauth/token",
    # `read,write` covers all read access plus issue/comment
    # creation and updates. Linear scopes are comma-separated.
    scope="read,write",
    scope_param="scope",
    extra_authorize_params={
        "response_type": "code",
        # `actor=user` (the default) makes the agent act as the
        # consenting user, not as the app — needed for "on behalf of."
        "actor": "user",
    },
    extract_credentials=_linear_extract_credentials,
    extract_refresh_credentials=_flat_refresh_extract,
)


PROVIDERS: dict[str, OAuthProvider] = {
    SLACK_PROVIDER.app_name: SLACK_PROVIDER,
    GOOGLE_CALENDAR_PROVIDER.app_name: GOOGLE_CALENDAR_PROVIDER,
    LINEAR_PROVIDER.app_name: LINEAR_PROVIDER,
}


def get_provider_for_app(app: ExternalApp) -> OAuthProvider | None:
    """Return the OAuth provider config for the given app row, or
    None if the app isn't a built-in OAuth provider."""
    return PROVIDERS.get(app.name)


def get_provider_or_raise(app: ExternalApp) -> OAuthProvider:
    """Same as `get_provider_for_app` but raises a 400 when the app
    isn't a built-in OAuth provider — for use in the OAuth route
    handlers where the unsupported case is user-visible."""
    provider = PROVIDERS.get(app.name)
    if provider is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"OAuth flow not configured for app '{app.name}'.",
        )
    return provider
