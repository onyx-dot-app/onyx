"""The authorization-code exchange of a built-in provider, shared by the Craft
app callback and the integration sign-in flow."""

from datetime import datetime, timezone
from typing import Any

import requests
from pydantic import BaseModel

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.base import OAuthExternalAppProvider, OAuthFlowSpec
from onyx.external_apps.token_utils import stamp_expires_at
from onyx.utils.logger import setup_logger

logger = setup_logger()


class PresetGrant(BaseModel):
    # Provider credentials with an absolute ``expires_at`` (ISO string).
    credentials: dict[str, Any]
    # None when the provider gives no signal.
    granted_scopes: list[str] | None


def exchange_preset_code(
    provider: OAuthExternalAppProvider,
    oauth: OAuthFlowSpec,
    *,
    app_name: str,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code_verifier: str | None,
) -> PresetGrant:
    token_request = provider.build_token_exchange_request(
        code,
        client_id,
        client_secret,
        redirect_uri,
        code_verifier=code_verifier,
    )
    try:
        response = requests.post(
            oauth.token_url,
            headers=token_request.headers,
            data=None if token_request.json_encoded else token_request.body,
            json=token_request.body if token_request.json_encoded else None,
            timeout=30,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        logger.warning("%s OAuth token exchange network error: %s", app_name, exc)
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            f"Could not reach {app_name} to complete OAuth.",
        )

    if 300 <= response.status_code < 400:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            f"{app_name} redirected its OAuth token request.",
        )

    try:
        response_data = response.json()
    except ValueError:
        logger.warning(
            "%s OAuth token response was not JSON (status=%d)",
            app_name,
            response.status_code,
        )
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            f"{app_name} returned a non-JSON response during OAuth.",
        )

    if not isinstance(response_data, dict):
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            f"{app_name} returned an invalid token response during OAuth.",
        )

    error = provider.classify_token_response(response, response_data)
    if error:
        logger.warning("%s OAuth token exchange failed: %s", app_name, error)
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            f"{app_name} OAuth failed: {error}",
        )

    credentials = provider.extract_credentials(response_data)
    access_token = credentials.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            f"{app_name} returned an invalid access token during OAuth.",
        )
    # An absolute `expires_at` lets the refresh path decide staleness later.
    return PresetGrant(
        credentials=stamp_expires_at(credentials, datetime.now(timezone.utc)),
        granted_scopes=provider.extract_granted_scopes(response_data),
    )
