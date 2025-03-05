from enum import Enum


class EmbeddingProvider(str, Enum):
    OPENAI = "openai"
    COHERE = "cohere"
    VOYAGE = "voyage"
    GOOGLE = "google"
    LITELLM = "litellm"
    AZURE = "azure"


class RerankerProvider(str, Enum):
    COHERE = "cohere"
    LITELLM = "litellm"
    BEDROCK = "bedrock"


class EmbedTextType(str, Enum):
    QUERY = "query"
    PASSAGE = "passage"
