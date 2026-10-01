"""
Constants for natural language processing, including embedding and reranking models.

This file contains constants moved from model_server to support the gradual migration
of API-based calls to bypass the model server.
"""

from shared_configs.enums import EmbeddingProvider, EmbedTextType

# Model used when a cloud embedding call gets no model name. Only the provider
# key test (test-embedding with an empty model_name) relies on this: stored
# search settings always carry a model name. OpenAI, Cohere and Google point at
# selectable models, so the key test checks access to a model an admin can
# still choose. Voyage cloud has no selectable model; its default is unchanged.
DEFAULT_OPENAI_MODEL = "text-embedding-3-small"
DEFAULT_COHERE_MODEL = "embed-v5.0-fast"
DEFAULT_VOYAGE_MODEL = "voyage-large-2-instruct"
DEFAULT_VERTEX_MODEL = "gemini-embedding-2"


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
