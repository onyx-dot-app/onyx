"""Cloud embedding provider access for the manual suites, from plain env vars only.

Nothing here reads ``.vscode/.env``, AWS Secrets Manager or any other secret
store. Export the variables yourself, or pass a gitignored env file with
``uv run --env-file``.
"""

import json
import os
from pathlib import Path

from shared_configs.enums import EmbeddingProvider

COHERE_API_KEY_ENV = "COHERE_API_KEY"
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
# A Google service-account JSON: the raw JSON string, or a path to the file.
VERTEX_CREDENTIALS_ENV = "VERTEX_CREDENTIALS"
# Optional. Onyx reads the Vertex location from the "location" key of the
# service-account JSON (then GOOGLE_CLOUD_LOCATION, then "global").
VERTEX_LOCATION_ENV = "VERTEX_LOCATION"

ENV_NAME_BY_PROVIDER: dict[EmbeddingProvider, str] = {
    EmbeddingProvider.COHERE: COHERE_API_KEY_ENV,
    EmbeddingProvider.OPENAI: OPENAI_API_KEY_ENV,
    EmbeddingProvider.GOOGLE: VERTEX_CREDENTIALS_ENV,
}


def provider_env_name(provider: EmbeddingProvider) -> str:
    env_name = ENV_NAME_BY_PROVIDER.get(provider)
    if env_name is None:
        raise ValueError(
            f"No env var is mapped for embedding provider {provider.value}. "
            "Add one to ENV_NAME_BY_PROVIDER."
        )
    return env_name


def _vertex_service_account_json(raw: str) -> str:
    text = raw
    if not raw.lstrip().startswith("{"):
        text = Path(raw).expanduser().read_text()
    info = json.loads(text)
    if not isinstance(info, dict):
        raise ValueError(f"{VERTEX_CREDENTIALS_ENV} must hold a JSON object.")
    location = os.environ.get(VERTEX_LOCATION_ENV, "").strip()
    if location:
        info["location"] = location
    return json.dumps(info)


def provider_api_key(provider: EmbeddingProvider) -> str | None:
    """The api_key Onyx stores for ``provider``, or None if its env var is unset.

    For Google this is the service-account JSON string, which is what the Onyx
    embedding provider stores as its api_key.
    """
    raw = os.environ.get(provider_env_name(provider), "").strip()
    if not raw:
        return None
    if provider == EmbeddingProvider.GOOGLE:
        return _vertex_service_account_json(raw)
    return raw
