import pytest

from onyx.configs.embedding_configs import SUPPORTED_EMBEDDING_MODELS


@pytest.mark.parametrize(
    "model_name",
    ["google/gemini-embedding-2", "google/gemini-embedding-2-preview"],
)
def test_supported_embedding_models_include_gemini_embedding_2(
    model_name: str,
) -> None:
    gemini_embedding_2_models = [
        model for model in SUPPORTED_EMBEDDING_MODELS if model.name == model_name
    ]

    assert len(gemini_embedding_2_models) == 1
    assert {model.dim for model in gemini_embedding_2_models} == {3072}
