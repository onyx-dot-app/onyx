import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.auth.credentials import Credentials

from onyx.natural_language_processing.embedding_auth import (
    VertexEmbeddingAuth,
    build_embedding_auth,
)
from onyx.natural_language_processing.embedding_providers.vertex_credentials import (
    VertexCredentialsCache,
)
from onyx.natural_language_processing.search_nlp_models import CloudEmbedding
from onyx.natural_language_processing.vertex_auth import VertexEmbeddingConfig
from shared_configs.enums import EmbeddingProvider

_CONFIG = VertexEmbeddingConfig(
    auth_method="service_account_json", project_id=None, location="us-central1"
)
_FROM_INFO = "google.oauth2.service_account.Credentials.from_service_account_info"


def _auth(project: str = "project-a") -> VertexEmbeddingAuth:
    key = json.dumps({"type": "service_account", "project_id": project})
    auth = build_embedding_auth(EmbeddingProvider.GOOGLE, key, _CONFIG)
    if not isinstance(auth, VertexEmbeddingAuth):
        raise TypeError("expected Vertex auth")
    return auth


def _new_credentials(*_args: object, **_kwargs: object) -> MagicMock:
    return MagicMock(spec=Credentials)


def test_credentials_resolve_once_per_configuration() -> None:
    cache = VertexCredentialsCache()
    with patch(_FROM_INFO, side_effect=_new_credentials) as from_info:
        first = cache.resolve(_auth())
        again = cache.resolve(_auth())
        other = cache.resolve(_auth("project-b"))

    assert again is first
    assert other is not first
    assert other.project_id == "project-b"
    assert from_info.call_count == 2


def test_full_cache_drops_the_entry_used_least_recently() -> None:
    cache = VertexCredentialsCache(max_entries=2)
    with patch(_FROM_INFO, side_effect=_new_credentials) as from_info:
        a = cache.resolve(_auth("a"))
        cache.resolve(_auth("b"))
        assert cache.resolve(_auth("a")) is a
        cache.resolve(_auth("c"))
        assert cache.resolve(_auth("a")) is a
        cache.resolve(_auth("b"))

    # a, b, c, then b again after c pushed it out.
    assert from_info.call_count == 4


def test_clear_resolves_again() -> None:
    cache = VertexCredentialsCache()
    with patch(_FROM_INFO, side_effect=_new_credentials) as from_info:
        first = cache.resolve(_auth())
        cache.clear()
        assert cache.resolve(_auth()) is not first

    assert from_info.call_count == 2


def test_credentials_key_does_not_contain_the_key() -> None:
    auth = _auth()
    assert "service_account" not in auth.credentials_key()
    assert auth.credentials_key() == _auth().credentials_key()
    assert auth.credentials_key() != _auth("project-b").credentials_key()


@pytest.mark.asyncio
async def test_embed_calls_share_resolved_credentials() -> None:
    client = MagicMock()
    response = MagicMock()
    response.embeddings = [MagicMock(values=[0.1, 0.2])]
    client.aio.models.embed_content = AsyncMock(return_value=response)
    client.aio.aclose = AsyncMock()
    key = json.dumps({"type": "service_account", "project_id": "project-a"})
    with (
        patch(_FROM_INFO, side_effect=_new_credentials) as from_info,
        patch("google.genai.Client", return_value=client),
    ):
        for _ in range(2):
            embedding = CloudEmbedding(key, EmbeddingProvider.GOOGLE)
            try:
                await embedding._embed_vertex(
                    ["text"], "text-embedding-005", "RETRIEVAL_QUERY", None
                )
            finally:
                await embedding.aclose()

    assert from_info.call_count == 1
