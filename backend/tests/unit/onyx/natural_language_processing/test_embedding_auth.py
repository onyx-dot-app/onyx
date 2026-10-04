from unittest.mock import patch

import pytest

from onyx.natural_language_processing.embedding_auth import (
    ApiKeyEmbeddingAuth,
    VertexEmbeddingAuth,
    build_embedding_auth,
)
from onyx.natural_language_processing.vertex_auth import VertexEmbeddingConfig
from shared_configs.enums import EmbeddingProvider


@pytest.mark.parametrize(
    "provider",
    [
        EmbeddingProvider.OPENAI,
        EmbeddingProvider.AZURE,
        EmbeddingProvider.COHERE,
        EmbeddingProvider.VOYAGE,
        EmbeddingProvider.LITELLM,
    ],
)
def test_api_key_providers_use_the_shared_auth_schema(
    provider: EmbeddingProvider,
) -> None:
    auth = build_embedding_auth(provider, "test-secret")
    assert isinstance(auth, ApiKeyEmbeddingAuth)
    assert auth.requires_api_key
    credentials = auth.resolve_credentials()
    assert credentials.api_key.get_secret_value() == "test-secret"
    assert "test-secret" not in credentials.model_dump_json()
    with pytest.raises(ValueError, match="API key not provided"):
        build_embedding_auth(provider, None).resolve_credentials()


def test_vertex_metadata_cannot_be_used_with_an_api_key_provider() -> None:
    with pytest.raises(ValueError, match="only supported for Google"):
        build_embedding_auth(
            EmbeddingProvider.OPENAI,
            "test-secret",
            VertexEmbeddingConfig(auth_method="workload_identity", project_id="target"),
        )


def test_workload_identity_validates_without_resolving_deployment_credentials() -> None:
    with patch("google.auth.default") as adc:
        auth = build_embedding_auth(
            EmbeddingProvider.GOOGLE,
            None,
            VertexEmbeddingConfig(auth_method="workload_identity", project_id="target"),
        )
        assert isinstance(auth, VertexEmbeddingAuth)
        assert not auth.requires_api_key
        auth.validate_credentials()
    adc.assert_not_called()


def test_legacy_google_auth_still_requires_a_json_key() -> None:
    auth = build_embedding_auth(EmbeddingProvider.GOOGLE, None)
    assert isinstance(auth, VertexEmbeddingAuth)
    assert auth.requires_api_key
    with pytest.raises(ValueError, match="Service account JSON is required"):
        auth.resolve_credentials()
