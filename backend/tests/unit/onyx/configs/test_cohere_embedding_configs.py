from onyx.configs.embedding_configs import SUPPORTED_EMBEDDING_MODELS


def test_supported_embedding_models_include_cohere_embed_v4() -> None:
    cohere_embed_v4_models = [
        model
        for model in SUPPORTED_EMBEDDING_MODELS
        if model.name == "cohere/embed-v4.0"
    ]

    # One FLOAT-precision entry and one BFLOAT16-precision entry per registered model.
    assert len(cohere_embed_v4_models) == 2
    assert {model.dim for model in cohere_embed_v4_models} == {1536}
