from enum import Enum


class EmbeddingProvider(str, Enum):
    OPENAI = "openai"
    COHERE = "cohere"
    VOYAGE = "voyage"
    GOOGLE = "google"


class RerankerProvider(str, Enum):
    COHERE = "cohere"


class EmbedTextType(str, Enum):
    QUERY = "query"
    PASSAGE = "passage"
