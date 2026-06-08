"""Bearer-token auth for the API server's /metrics endpoint.

Auth is required by default. Scrapers must present ``METRICS_AUTH_TOKEN`` as
``Authorization: Bearer <token>`` — the standard Prometheus scrape format
(``authorization: { credentials: <token> }`` in a scrape config).

Set ``DISABLE_METRICS_AUTH=true`` to deliberately expose /metrics with no
authentication. If neither the token nor the opt-out is set, /metrics is locked
(every request gets 401) so it can never be exposed by accident.
"""

import secrets

from fastapi import Request

from onyx.auth.constants import BEARER_PREFIX
from onyx.configs.app_configs import DISABLE_METRICS_AUTH
from onyx.configs.app_configs import METRICS_AUTH_TOKEN
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

# RFC 6750 §3: a 401 from a bearer-protected resource must advertise the scheme.
_WWW_AUTHENTICATE = {"WWW-Authenticate": "Bearer"}


def verify_metrics_token(request: Request) -> None:
    """FastAPI dependency guarding the /metrics endpoint.

    No-op only when ``DISABLE_METRICS_AUTH`` is set. Otherwise a matching bearer
    token is required: if ``METRICS_AUTH_TOKEN`` is unset the endpoint is locked,
    and any missing/invalid token raises ``OnyxError(UNAUTHENTICATED)``. The token
    comparison is constant-time to avoid leaking it via response timing.
    """
    if DISABLE_METRICS_AUTH:
        return

    expected = METRICS_AUTH_TOKEN
    if not expected:
        # Fail secure: auth is required but no token is configured, so there is
        # no valid credential. Lock the endpoint rather than exposing it.
        raise OnyxError(
            OnyxErrorCode.UNAUTHENTICATED,
            "/metrics auth not configured; set METRICS_AUTH_TOKEN or "
            "DISABLE_METRICS_AUTH",
            headers=_WWW_AUTHENTICATE,
        )

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith(BEARER_PREFIX):
        raise OnyxError(
            OnyxErrorCode.UNAUTHENTICATED,
            "Missing or invalid metrics bearer token",
            headers=_WWW_AUTHENTICATE,
        )

    provided = auth_header[len(BEARER_PREFIX) :].strip()
    if not secrets.compare_digest(provided, expected):
        raise OnyxError(
            OnyxErrorCode.UNAUTHENTICATED,
            "Invalid metrics bearer token",
            headers=_WWW_AUTHENTICATE,
        )
