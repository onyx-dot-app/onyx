"""Provision-time validation of SANDBOX_API_SERVER_URL.

SANDBOX_API_SERVER_URL is the full base URL a sandbox client uses, any API
path prefix included. The classic misconfiguration is a public URL without
its /api prefix, which fails far from the cause: every LLM-gateway and
onyx-cli call inside the sandbox 404s. Probe once per process at provision
time and fail with the corrected value instead.
"""

import threading

import httpx

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.logger import setup_logger

logger = setup_logger()

_PROBE_TIMEOUT_SECONDS = 5.0

_validated = False
_validated_lock = threading.Lock()


def _probe_health(base_url: str) -> httpx.Response | None:
    """Response of GET {base_url}/health, or None when unreachable."""
    try:
        return httpx.get(
            f"{base_url}/health",
            timeout=_PROBE_TIMEOUT_SECONDS,
            follow_redirects=True,
        )
    except httpx.HTTPError:
        return None


def _is_health_response(response: httpx.Response) -> bool:
    """True only for the API server's real /health payload (StatusResponse).

    Status code alone is not enough: an ingress can redirect the unprefixed
    path to a login/web page that answers 200, which would mask the missing
    /api prefix.
    """
    if response.status_code != 200:
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    return isinstance(body, dict) and body.get("success") is True


def validate_sandbox_api_url(api_server_url: str) -> None:
    """Fail provisioning when the URL provably lacks its API path prefix.

    Evidence-based, never shape-guessing: raises only when {url}/health does
    not serve the API health payload while {url}/api/health does. An
    unreachable or ambiguous probe (egress quirks, hairpin NAT, WAF-guarded
    health) logs a warning and passes — this check must never block a working
    deployment.
    """
    global _validated
    if _validated:
        return

    base = api_server_url.rstrip("/")
    response = _probe_health(base)
    if response is None:
        logger.warning(
            "Could not probe %s/health to validate SANDBOX_API_SERVER_URL; "
            "skipping the prefix check",
            base,
        )
        return
    if _is_health_response(response):
        with _validated_lock:
            _validated = True
        return
    # 404s and 2xx responses that are not the health payload (an ingress
    # serving a login/web page for the unprefixed path) both suggest a
    # missing prefix. Anything else (401/403/5xx) is ambiguous — a WAF may
    # guard /health — so pass rather than risk blocking a working deployment.
    if response.status_code != 404 and not (200 <= response.status_code < 300):
        with _validated_lock:
            _validated = True
        return

    prefixed = f"{base}/api"
    prefixed_response = _probe_health(prefixed)
    if prefixed_response is not None and _is_health_response(prefixed_response):
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            f"SANDBOX_API_SERVER_URL={api_server_url!r} is missing its API path "
            f"prefix: {base}/health does not serve the API health payload "
            f"(HTTP {response.status_code}) while {prefixed}/health does. "
            f"Set SANDBOX_API_SERVER_URL to {prefixed!r} — the full base URL a "
            "sandbox client uses.",
        )
    logger.warning(
        "SANDBOX_API_SERVER_URL=%s: %s/health did not serve the API health "
        "payload (HTTP %s) and %s/health did not either; sandbox API calls "
        "will likely fail. Verify the URL is the full base URL including any "
        "path prefix.",
        api_server_url,
        base,
        response.status_code,
        prefixed,
    )
