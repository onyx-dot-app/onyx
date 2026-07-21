"""Provision-time validation of SANDBOX_API_SERVER_URL.

SANDBOX_API_SERVER_URL is the full base URL a sandbox client uses, any API
path prefix included. The classic misconfiguration is a public URL without
its /api prefix, which fails far from the cause: every LLM-gateway and
onyx-cli call inside the sandbox 404s. Probe once per process at provision
time and fail with the corrected value instead.
"""

import threading

import httpx

from onyx.utils.logger import setup_logger

logger = setup_logger()

_PROBE_TIMEOUT_SECONDS = 5.0

_validated = False
_validated_lock = threading.Lock()


def _probe_health(base_url: str) -> int | None:
    """Status of GET {base_url}/health, or None when unreachable."""
    try:
        return httpx.get(
            f"{base_url}/health",
            timeout=_PROBE_TIMEOUT_SECONDS,
            follow_redirects=True,
        ).status_code
    except httpx.HTTPError:
        return None


def validate_sandbox_api_url(api_server_url: str) -> None:
    """Fail provisioning when the URL provably lacks its API path prefix.

    Evidence-based, never shape-guessing: raises only when {url}/health
    404s while {url}/api/health responds. An unreachable probe (egress
    quirks, hairpin NAT) logs a warning and passes — this check must never
    block a working deployment.
    """
    global _validated
    if _validated:
        return

    base = api_server_url.rstrip("/")
    status = _probe_health(base)
    if status is None:
        logger.warning(
            "Could not probe %s/health to validate SANDBOX_API_SERVER_URL; "
            "skipping the prefix check",
            base,
        )
        return
    if status != 404:
        with _validated_lock:
            _validated = True
        return

    prefixed = f"{base}/api"
    prefixed_status = _probe_health(prefixed)
    if prefixed_status is not None and prefixed_status != 404:
        raise RuntimeError(
            f"SANDBOX_API_SERVER_URL={api_server_url!r} is missing its API path "
            f"prefix: {base}/health returns 404 while {prefixed}/health responds. "
            f"Set SANDBOX_API_SERVER_URL to {prefixed!r} — the full base URL a "
            "sandbox client uses."
        )
    logger.warning(
        "SANDBOX_API_SERVER_URL=%s: %s/health returned 404 and %s/health did "
        "not respond either; sandbox API calls will likely fail. Verify the "
        "URL is the full base URL including any path prefix.",
        api_server_url,
        base,
        prefixed,
    )
