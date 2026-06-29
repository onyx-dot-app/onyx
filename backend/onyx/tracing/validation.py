"""Best-effort credential validation for tracing providers (used by /test)."""

from __future__ import annotations

from onyx.utils.logger import setup_logger
from shared_configs.enums import TracingProviderType

logger = setup_logger()


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
    import braintrust

    try:
        braintrust.login(api_key=api_key)
    except Exception as e:
        raise ValueError(f"Braintrust credential check failed: {e}") from e


def _validate_langfuse(secret_key: str, config: dict[str, str]) -> None:
    public_key = config.get("public_key")
    if not public_key:
        raise ValueError("Langfuse requires both a secret key and a public key.")

    from langfuse import Langfuse

    try:
        client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=config.get("host") or None,
        )
        if not client.auth_check():
            raise ValueError("Langfuse rejected the provided credentials.")
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Langfuse credential check failed: {e}") from e
