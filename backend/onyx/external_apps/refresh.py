"""Pure HTTP refresh-token exchange.

No DB, no transaction handling, no decision about *whether* to
refresh — just the network call to the provider's token endpoint and
the response parse. Callers (the db-side `refresh_credentials`
helper) are responsible for locking, the decision, and persistence.
"""

from typing import Any

import requests

from onyx.external_apps.providers import OAuthProvider
from onyx.utils.logger import setup_logger

logger = setup_logger()


def refresh_oauth_tokens(
    provider: OAuthProvider,
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> dict[str, Any] | None:
    """POST `grant_type=refresh_token` to the provider's token URL.

    Returns the parsed dict of fields to merge into the user's stored
    credentials (e.g. `{access_token, expires_in, refresh_token?}`),
    or None if the provider rejected the refresh — revoked refresh
    token, network error, malformed response, etc. The caller treats
    None as "user must re-authenticate."
    """
    try:
        response = requests.post(
            provider.token_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        logger.warning(
            "%s refresh request failed at network layer: %s",
            provider.app_name,
            exc,
        )
        return None

    try:
        body = response.json()
    except ValueError:
        logger.warning(
            "%s refresh response was not JSON (status=%d)",
            provider.app_name,
            response.status_code,
        )
        return None

    # Cross-provider error detection. Slack returns 200 with
    # `{"ok": false, "error": "..."}` on failure; everyone else
    # (Google, Linear, OAuth-spec-compliant providers) uses non-2xx.
    if response.status_code >= 400 or body.get("ok") is False:
        error = body.get("error_description") or body.get("error") or "unknown"
        logger.warning("%s refresh failed: %s", provider.app_name, error)
        return None

    return provider.extract_refresh_credentials(body)
