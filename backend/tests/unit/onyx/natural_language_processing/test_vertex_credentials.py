import json
import threading
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


def _auth(
    project: str = "project-a", config: VertexEmbeddingConfig = _CONFIG
) -> VertexEmbeddingAuth:
    key = json.dumps({"type": "service_account", "project_id": project})
    auth = build_embedding_auth(EmbeddingProvider.GOOGLE, key, config)
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


def test_same_key_with_another_configuration_resolves_again() -> None:
    cache = VertexCredentialsCache()
    other_config = VertexEmbeddingConfig(
        auth_method="service_account_json", project_id=None, location="europe-west4"
    )
    assert _auth().credentials_key() != _auth(config=other_config).credentials_key()
    with patch(_FROM_INFO, side_effect=_new_credentials) as from_info:
        first = cache.resolve(_auth())
        other = cache.resolve(_auth(config=other_config))

    assert other is not first
    assert first.location == "us-central1"
    assert other.location == "europe-west4"
    assert from_info.call_count == 2


def test_workload_identity_resolves_once_per_configuration() -> None:
    def auth(project: str) -> VertexEmbeddingAuth:
        config = VertexEmbeddingConfig(
            auth_method="workload_identity", project_id=project, location="global"
        )
        built = build_embedding_auth(EmbeddingProvider.GOOGLE, None, config)
        if not isinstance(built, VertexEmbeddingAuth):
            raise TypeError("expected Vertex auth")
        return built

    cache = VertexCredentialsCache()
    with patch(
        "google.auth.default",
        side_effect=lambda **_kwargs: (MagicMock(spec=Credentials), "pod-project"),
    ) as default:
        first = cache.resolve(auth("project-a"))
        again = cache.resolve(auth("project-a"))
        other = cache.resolve(auth("project-b"))

    assert again is first
    assert other is not first
    assert other.project_id == "project-b"
    assert default.call_count == 2


def test_concurrent_misses_for_one_key_resolve_once() -> None:
    cache = VertexCredentialsCache()
    thread_count = 4
    in_resolve = threading.Event()
    finish_resolve = threading.Event()
    results: list[object] = []

    def slow_credentials(*_args: object, **_kwargs: object) -> MagicMock:
        in_resolve.set()
        finish_resolve.wait(timeout=10)
        return MagicMock(spec=Credentials)

    def resolve() -> None:
        results.append(cache.resolve(_auth()))

    with patch(_FROM_INFO, side_effect=slow_credentials) as from_info:
        first = threading.Thread(target=resolve)
        first.start()
        try:
            assert in_resolve.wait(timeout=10)
            # The first thread is in its resolve. These calls must wait for it.
            others = [threading.Thread(target=resolve) for _ in range(thread_count - 1)]
            for thread in others:
                thread.start()
        finally:
            finish_resolve.set()
            first.join(timeout=10)
        for thread in others:
            thread.join(timeout=10)

    assert from_info.call_count == 1
    assert len(results) == thread_count
    assert all(result is results[0] for result in results)


def test_failed_resolve_is_not_cached() -> None:
    cache = VertexCredentialsCache()
    with patch(
        _FROM_INFO, side_effect=[ValueError("bad key"), MagicMock(spec=Credentials)]
    ) as from_info:
        with pytest.raises(ValueError):
            cache.resolve(_auth())
        cache.resolve(_auth())

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
