"""The provider key test (POST /admin/embedding/test-embedding with an empty
model_name) embeds with these defaults. They must be models an admin can still
choose, so a passing key test means the key works for a selectable model."""

import pytest

from onyx.natural_language_processing.constants import (
    DEFAULT_COHERE_MODEL,
    DEFAULT_OPENAI_MODEL,
    DEFAULT_VERTEX_MODEL,
    DEFAULT_VOYAGE_MODEL,
)
from shared_configs.embedding_models import (
    EmbeddingModelStatus,
    find_embedding_model_spec,
)
from shared_configs.enums import EmbeddingProvider


@pytest.mark.parametrize(
    ("provider_type", "model_name"),
    [
        (EmbeddingProvider.OPENAI, DEFAULT_OPENAI_MODEL),
        (EmbeddingProvider.COHERE, DEFAULT_COHERE_MODEL),
        (EmbeddingProvider.GOOGLE, DEFAULT_VERTEX_MODEL),
    ],
)
def test_probe_default_is_a_selectable_model(
    provider_type: EmbeddingProvider, model_name: str
) -> None:
    spec = find_embedding_model_spec(provider_type, model_name)

    assert spec is not None
    assert spec.status == EmbeddingModelStatus.SELECTABLE
    assert spec.model_name == model_name


def test_probe_defaults() -> None:
    assert DEFAULT_OPENAI_MODEL == "text-embedding-3-small"
    assert DEFAULT_COHERE_MODEL == "embed-v5.0-fast"
    assert DEFAULT_VERTEX_MODEL == "gemini-embedding-2"
    # Voyage cloud has no selectable model, so its default stays.
    assert DEFAULT_VOYAGE_MODEL == "voyage-large-2-instruct"
