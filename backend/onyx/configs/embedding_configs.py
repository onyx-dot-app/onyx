from pydantic import BaseModel

from onyx.db.enums import EmbeddingPrecision


class _BaseEmbeddingModel(BaseModel):
    """Private model for defining base embedding model configurations."""

    name: str
    dim: int
    index_name: str


class SupportedEmbeddingModel(BaseModel):
    name: str
    dim: int
    index_name: str
    embedding_precision: EmbeddingPrecision


# Base embedding model configurations (without precision)
_BASE_EMBEDDING_MODELS = [
    # Cloud-based models
    _BaseEmbeddingModel(
        name="cohere/embed-english-v3.0",
        dim=1024,
        index_name="danswer_chunk_cohere_embed_english_v3_0",
    ),
    _BaseEmbeddingModel(
        name="cohere/embed-english-v3.0",
        dim=1024,
        index_name="danswer_chunk_embed_english_v3_0",
    ),
    _BaseEmbeddingModel(
        name="cohere/embed-english-light-v3.0",
        dim=384,
        index_name="danswer_chunk_cohere_embed_english_light_v3_0",
    ),
    _BaseEmbeddingModel(
        name="cohere/embed-english-light-v3.0",
        dim=384,
        index_name="danswer_chunk_embed_english_light_v3_0",
    ),
    _BaseEmbeddingModel(
        name="openai/text-embedding-3-large",
        dim=3072,
        index_name="danswer_chunk_openai_text_embedding_3_large",
    ),
    _BaseEmbeddingModel(
        name="openai/text-embedding-3-large",
        dim=3072,
        index_name="danswer_chunk_text_embedding_3_large",
    ),
    _BaseEmbeddingModel(
        name="openai/text-embedding-3-small",
        dim=1536,
        index_name="danswer_chunk_openai_text_embedding_3_small",
    ),
    _BaseEmbeddingModel(
        name="openai/text-embedding-3-small",
        dim=1536,
        index_name="danswer_chunk_text_embedding_3_small",
    ),
    _BaseEmbeddingModel(
        name="google/gemini-embedding-001",
        dim=3072,
        index_name="danswer_chunk_google_gemini_embedding_001",
    ),
    _BaseEmbeddingModel(
        name="google/text-embedding-005",
        dim=768,
        index_name="danswer_chunk_google_text_embedding_005",
    ),
    _BaseEmbeddingModel(
        name="voyage/voyage-large-2-instruct",
        dim=1024,
        index_name="danswer_chunk_voyage_large_2_instruct",
    ),
    _BaseEmbeddingModel(
        name="voyage/voyage-large-2-instruct",
        dim=1024,
        index_name="danswer_chunk_large_2_instruct",
    ),
    _BaseEmbeddingModel(
        name="voyage/voyage-light-2-instruct",
        dim=384,
        index_name="danswer_chunk_voyage_light_2_instruct",
    ),
    _BaseEmbeddingModel(
        name="voyage/voyage-light-2-instruct",
        dim=384,
        index_name="danswer_chunk_light_2_instruct",
    ),
    # Self-hosted models
    _BaseEmbeddingModel(
        name="nomic-ai/nomic-embed-text-v1",
        dim=768,
        index_name="danswer_chunk_nomic_ai_nomic_embed_text_v1",
    ),
    _BaseEmbeddingModel(
        name="nomic-ai/nomic-embed-text-v1",
        dim=768,
        index_name="danswer_chunk_nomic_embed_text_v1",
    ),
    _BaseEmbeddingModel(
        name="intfloat/e5-base-v2",
        dim=768,
        index_name="danswer_chunk_intfloat_e5_base_v2",
    ),
    _BaseEmbeddingModel(
        name="intfloat/e5-small-v2",
        dim=384,
        index_name="danswer_chunk_intfloat_e5_small_v2",
    ),
    _BaseEmbeddingModel(
        name="intfloat/multilingual-e5-base",
        dim=768,
        index_name="danswer_chunk_intfloat_multilingual_e5_base",
    ),
    _BaseEmbeddingModel(
        name="intfloat/multilingual-e5-small",
        dim=384,
        index_name="danswer_chunk_intfloat_multilingual_e5_small",
    ),
]

# Automatically generate both FLOAT and BFLOAT16 versions of all models
SUPPORTED_EMBEDDING_MODELS = [
    # BFLOAT16 precision versions
    *[
        SupportedEmbeddingModel(
            name=model.name,
            dim=model.dim,
            index_name=f"{model.index_name}_bfloat16",
            embedding_precision=EmbeddingPrecision.BFLOAT16,
        )
        for model in _BASE_EMBEDDING_MODELS
    ],
    # FLOAT precision versions
    # NOTE: need to keep this one for backwards compatibility. We now default to
    # BFLOAT16.
    *[
        SupportedEmbeddingModel(
            name=model.name,
            dim=model.dim,
            index_name=model.index_name,
            embedding_precision=EmbeddingPrecision.FLOAT,
        )
        for model in _BASE_EMBEDDING_MODELS
    ],
]
