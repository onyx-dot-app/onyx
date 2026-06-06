"""Auth for the Prometheus ``/metrics`` endpoint.

The endpoint is scraped by machines (e.g. a Prometheus ServiceMonitor) that
cannot present a session cookie, so it is protected with a static Bearer token
rather than user auth. When ``METRICS_AUTH_TOKEN`` is unset the endpoint is open
(backwards-compatible default); when set, callers must send
``Authorization: Bearer <token>`` (Oneleet pentest finding ON-010 / ENG-4131).
"""

import secrets

from fastapi import Header

from onyx.auth.constants import BEARER_PREFIX
from onyx.configs.app_configs import METRICS_AUTH_TOKEN
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


async def verify_metrics_token(
    authorization: str | None = Header(default=None),
) -> None:
    """Reject /metrics requests that don't carry the configured Bearer token.

    No-op when ``METRICS_AUTH_TOKEN`` is unset.
    """
    if not METRICS_AUTH_TOKEN:
        return

    if not authorization or not authorization.startswith(BEARER_PREFIX):
        raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)

    token = authorization[len(BEARER_PREFIX) :].strip()
    if not secrets.compare_digest(token, METRICS_AUTH_TOKEN):
        raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)
