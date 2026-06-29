"""Best-effort credential validation for tracing providers (used by /test).

Validation hits each provider's REST API directly with the supplied credentials
rather than the provider SDKs. The SDK entry points (e.g. ``braintrust.login``)
mutate process-global state, so calling them here would let a test key clobber the
live tracing client; a plain authenticated request has no such side effect.
"""

from __future__ import annotations

import requests

from onyx.utils.logger import setup_logger
from shared_configs.enums import TracingProviderType

logger = setup_logger()

_VALIDATION_TIMEOUT_S = 10
_BRAINTRUST_API_URL = "https://api.braintrust.dev"
_LANGFUSE_DEFAULT_HOST = "https://cloud.langfuse.com"


def validate_tracing_credentials(
    *,
    provider_type: TracingProviderType,
    api_key: str | None,
    config: dict[str, str],
) -> None:
    """Raise ValueError if the credentials are missing or rejected by the provider."""
    if not api_key:
        raise ValueError("API key is required.")

    if provider_type == TracingProviderType.BRAINTRUST:
        _validate_braintrust(api_key)
    elif provider_type == TracingProviderType.LANGFUSE:
        _validate_langfuse(api_key, config)


def _validate_braintrust(api_key: str) -> None:
    try:
        resp = requests.get(
            f"{_BRAINTRUST_API_URL}/v1/project",
            headers={"Authorization": f"Bearer {api_key}"},
            params={"limit": 1},
            timeout=_VALIDATION_TIMEOUT_S,
        )
    except requests.RequestException as e:
        raise ValueError(f"Could not reach Braintrust: {e}") from e

    if resp.status_code in (401, 403):
        raise ValueError("Braintrust rejected the provided API key.")
    if not resp.ok:
        raise ValueError(
            f"Braintrust credential check failed (HTTP {resp.status_code})."
        )


def _validate_langfuse(secret_key: str, config: dict[str, str]) -> None:
    public_key = config.get("public_key")
    if not public_key:
        raise ValueError("Langfuse requires both a secret key and a public key.")

    host = (config.get("host") or _LANGFUSE_DEFAULT_HOST).rstrip("/")
    try:
        # Langfuse's public API uses Basic auth (public key + secret key).
        resp = requests.get(
            f"{host}/api/public/projects",
            auth=(public_key, secret_key),
            timeout=_VALIDATION_TIMEOUT_S,
        )
    except requests.RequestException as e:
        raise ValueError(f"Could not reach Langfuse: {e}") from e

    if resp.status_code in (401, 403):
        raise ValueError("Langfuse rejected the provided credentials.")
    if not resp.ok:
        raise ValueError(f"Langfuse credential check failed (HTTP {resp.status_code}).")
