"""
Constants for natural language processing, including embedding and reranking models.

This file contains constants moved from model_server to support the gradual migration
of API-based calls to bypass the model server.
"""

from shared_configs.enums import EmbeddingProvider
from shared_configs.enums import EmbedTextType


# Default model names for different providers
DEFAULT_OPENAI_MODEL = "text-embedding-3-small"
DEFAULT_COHERE_MODEL = "embed-english-light-v3.0"
DEFAULT_VOYAGE_MODEL = "voyage-large-2-instruct"
DEFAULT_VERTEX_MODEL = "text-embedding-005"


class EmbeddingModelTextType:
    """Mapping of Onyx text types to provider-specific text types."""

    PROVIDER_TEXT_TYPE_MAP = {
        EmbeddingProvider.COHERE: {
            EmbedTextType.QUERY: "search_query",
            EmbedTextType.PASSAGE: "search_document",
        },
        EmbeddingProvider.VOYAGE: {
            EmbedTextType.QUERY: "query",
            EmbedTextType.PASSAGE: "document",
        },
        EmbeddingProvider.GOOGLE: {
            EmbedTextType.QUERY: "RETRIEVAL_QUERY",
            EmbedTextType.PASSAGE: "RETRIEVAL_DOCUMENT",
        },
    }

    @staticmethod
    def get_type(provider: EmbeddingProvider, text_type: EmbedTextType) -> str:
        """Get provider-specific text type string."""
        return EmbeddingModelTextType.PROVIDER_TEXT_TYPE_MAP[provider][text_type]
