"""HTTP refresh-token exchange. No DB, no decision logic — callers
own locking and persistence."""

from typing import Any

import requests

from onyx.external_apps.providers import OAuth
from onyx.external_apps.providers import Refresh
from onyx.utils.logger import setup_logger

logger = setup_logger()


def refresh_oauth_tokens(
    provider: OAuth,
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> dict[str, Any] | None:
    """Returns the fields to merge into stored credentials, or None
    if the provider doesn't support refresh or the upstream rejected
    it. Caller treats None as "user must re-authenticate."
    """
    if not isinstance(provider, Refresh):
        logger.warning(
            "%s does not implement Refresh; cannot refresh tokens",
            provider.app_name,
        )
        return None

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

    # Slack returns 200 + `{"ok": false}` on failure; everyone else
    # uses non-2xx.
    if response.status_code >= 400 or body.get("ok") is False:
        error = body.get("error_description") or body.get("error") or "unknown"
        logger.warning("%s refresh failed: %s", provider.app_name, error)
        return None

    return provider.extract_refresh_credentials(body)
