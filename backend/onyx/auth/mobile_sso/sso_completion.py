"""Shared SSO completion for native mobile clients.

Every OAuth/SSO provider callback (Google today; OIDC / SAML / Apple later)
funnels through ``complete_mobile_sso`` once the signed state carries the mobile
marker. It mints the session token, stashes it behind a single-use PKCE-bound
code, and 302-redirects to the app's custom-scheme deep link carrying ONLY that
code (plus the app's own ``state`` for round-trip verification).

The mobile params travel inside the signed OAuth state token (see
``apply_mobile_state``), so they are tamper-proof through the IdP round-trip and
need no separate cookie. ``is_mobile_sso`` / ``apply_mobile_state`` keep the
state-key spelling private to this module — callers never touch the raw keys.
"""

from typing import cast

from fastapi.responses import RedirectResponse
from fastapi_users import models
from fastapi_users.authentication import Strategy

from onyx.auth.mobile_sso.code_store import store_sso_code
from onyx.auth.mobile_sso.tokens import issue_session_credential
from onyx.configs.app_configs import MOBILE_ALLOWED_REDIRECT_URIS
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.logger import setup_logger
from onyx.utils.url import add_url_params

logger = setup_logger()

# Keys carried (tamper-proof) inside the signed OAuth state token. Private to
# this module so the spelling lives in exactly one place.
_STATE_CLIENT_KEY = "client"
_STATE_APP_REDIRECT_URI_KEY = "app_redirect_uri"
_STATE_APP_STATE_KEY = "app_state"
_STATE_APP_CODE_CHALLENGE_KEY = "app_code_challenge"
_MOBILE_CLIENT_MARKER = "mobile"


def apply_mobile_state(
    state_data: dict[str, str],
    mobile_redirect_uri: str | None,
    app_state: str | None,
    app_code_challenge: str | None,
) -> None:
    """Fold guarded mobile-SSO params into the (about-to-be-signed) OAuth state.

    No-op for the web flow (``mobile_redirect_uri`` absent), so the signed state
    is byte-identical to today's for every non-mobile caller. For a mobile caller
    the params are validated here — failing fast at authorize-time so a bad
    request is rejected before the IdP round-trip rather than after it. Raises
    ``OnyxError(VALIDATION_ERROR)`` on a missing challenge / disallowed URI.
    """
    if mobile_redirect_uri is None:
        return
    _validate_mobile_sso_params(mobile_redirect_uri, app_code_challenge)
    state_data[_STATE_CLIENT_KEY] = _MOBILE_CLIENT_MARKER
    state_data[_STATE_APP_REDIRECT_URI_KEY] = mobile_redirect_uri
    state_data[_STATE_APP_STATE_KEY] = app_state or ""
    # Non-None and validated above.
    state_data[_STATE_APP_CODE_CHALLENGE_KEY] = cast(str, app_code_challenge)


def _validate_mobile_sso_params(
    app_redirect_uri: str | None, app_code_challenge: str | None
) -> None:
    """Enforce the mobile-SSO invariants (PKCE-only + allowlisted redirect URI).

    Used at authorize-time (fail fast) and again in ``complete_mobile_sso`` as a
    defensive backstop against any path that fills the state directly.
    """
    if not app_code_challenge:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            "Mobile SSO requires a PKCE code challenge",
        )
    if not app_redirect_uri or app_redirect_uri not in MOBILE_ALLOWED_REDIRECT_URIS:
        # A redirect URI isn't a secret; log it + the allowlist so a misconfig
        # is diagnosable instead of a silent 400.
        logger.warning(
            "Rejected mobile SSO redirect URI %r; allowed: %s",
            app_redirect_uri,
            MOBILE_ALLOWED_REDIRECT_URIS,
        )
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            "Disallowed mobile redirect URI",
        )


def is_mobile_sso(state_data: dict[str, str]) -> bool:
    return state_data.get(_STATE_CLIENT_KEY) == _MOBILE_CLIENT_MARKER


async def complete_mobile_sso(
    user: models.UP,
    state_data: dict[str, str],
    strategy: Strategy[models.UP, models.ID],
) -> RedirectResponse:
    """Finish an SSO login for a mobile client: mint -> store-under-code -> 302.

    Requires an app-supplied PKCE challenge (mobile SSO is PKCE-only — we never
    silently fall back to a non-PKCE code) and an allowlisted redirect URI.
    Raises ``OnyxError(VALIDATION_ERROR)`` otherwise. Notably mints the token but
    does NOT call ``backend.login``, so no web auth cookie is ever set.
    """
    app_redirect_uri = state_data.get(_STATE_APP_REDIRECT_URI_KEY)
    app_code_challenge = state_data.get(_STATE_APP_CODE_CHALLENGE_KEY)
    app_state = state_data.get(_STATE_APP_STATE_KEY, "")

    # Backstop: these are already enforced at authorize-time (apply_mobile_state),
    # but re-check so any path that fills the state directly still fails closed.
    _validate_mobile_sso_params(app_redirect_uri, app_code_challenge)
    app_redirect_uri = cast(str, app_redirect_uri)
    app_code_challenge = cast(str, app_code_challenge)

    token = await issue_session_credential(user, strategy)
    code = await store_sso_code(token, app_code_challenge)

    deep_link = add_url_params(app_redirect_uri, {"code": code, "state": app_state})
    return RedirectResponse(deep_link, status_code=302)
