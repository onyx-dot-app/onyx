"""OAuth refresh error taxonomy and the shared token-response classifier.

Terminal-vs-transient is the contract every refresher agrees on: a *terminal*
failure means the grant is dead (reconnect required), a *transient* one means
retry later with the existing token still in place.
"""

from typing import Any

import requests


class TokenRefreshError(Exception):
    """Base class for OAuth access-token refresh failures."""


class TokenRefreshTerminalError(TokenRefreshError):
    """The refresh token is dead (revoked / invalid_grant / missing). The stored
    credential should be cleared and the user prompted to reconnect — retrying
    cannot succeed."""


class TokenRefreshTransientError(TokenRefreshError):
    """A transient failure (network, 5xx, non-JSON, rate-limit). The existing
    token should be left in place and the refresh retried on a later request."""


def token_response_error(http_response: requests.Response, body: Any) -> str | None:
    """Slack returns 200 + ``{"ok": false}`` on failure; everyone else uses
    non-2xx. Returns the error string or ``None`` on success.

    ``body`` is whatever ``response.json()`` produced, so it may not be a JSON
    object (a gateway can return a bare array / string / number / ``null``). A
    non-object can't carry an OAuth error code, so a non-2xx is reported as a
    generic failure and a 2xx falls through to credential mapping — never an
    unguarded ``.get()`` that would escape the refresh error handling."""
    if not isinstance(body, dict):
        if http_response.status_code >= 400:
            return f"unexpected token response (status={http_response.status_code})"
        return None
    if http_response.status_code >= 400:
        # Prefer the machine-readable `error` code over the human-readable
        # `error_description`: terminal-vs-transient classification matches against
        # OAuth error codes (e.g. `invalid_grant`), so returning the prose would
        # misclassify a dead grant as transient and skip required reconnect handling.
        return body.get("error") or body.get("error_description") or "unknown"
    if body.get("ok") is False:
        return body.get("error") or "unknown"
    return None
