from onyx.configs.embedding_configs import SUPPORTED_EMBEDDING_MODELS


def test_supported_embedding_models_include_gemini_embedding_2_preview() -> None:
    gemini_embedding_2_models = [
        model
        for model in SUPPORTED_EMBEDDING_MODELS
        if model.name == "google/gemini-embedding-2-preview"
    ]

    # One FLOAT-precision entry and one BFLOAT16-precision entry per registered model.
    assert len(gemini_embedding_2_models) == 2
    assert {model.dim for model in gemini_embedding_2_models} == {3072}
