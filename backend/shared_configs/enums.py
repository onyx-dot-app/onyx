from enum import Enum


class EmbeddingProvider(str, Enum):
    OPENAI = "openai"
    COHERE = "cohere"
    VOYAGE = "voyage"
    GOOGLE = "google"
    LITELLM = "litellm"


class RerankerProvider(str, Enum):
    COHERE = "cohere"
    LITELLM = "litellm"


class EmbedTextType(str, Enum):
    QUERY = "query"
    PASSAGE = "passage"
