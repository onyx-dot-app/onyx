"""Cloud embedding keys for the manual suites, from plain env vars only."""

import os
from pathlib import Path

import pytest

from shared_configs.enums import EmbeddingProvider

KEY_ENV_BY_PROVIDER: dict[EmbeddingProvider, str] = {
    EmbeddingProvider.COHERE: "COHERE_API_KEY",
    EmbeddingProvider.OPENAI: "OPENAI_API_KEY",
    EmbeddingProvider.VOYAGE: "VOYAGE_API_KEY",
    # The path to a Google service-account JSON file.
    EmbeddingProvider.GOOGLE: "VERTEX_CREDENTIALS",
}


def provider_api_key(provider: EmbeddingProvider) -> str:
    """The api_key that Onyx stores for ``provider``. Skips the test if unset."""
    env_name = KEY_ENV_BY_PROVIDER[provider]
    value = os.environ.get(env_name, "").strip()
    if not value:
        pytest.skip(f"{env_name} is not set.")
    if provider == EmbeddingProvider.GOOGLE:
        # Onyx stores the service-account JSON itself as the Google api_key.
        return Path(value).expanduser().read_text()
    return value
