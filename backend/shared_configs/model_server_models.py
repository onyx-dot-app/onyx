from pydantic import BaseModel

from shared_configs.enums import EmbeddingProvider
from shared_configs.enums import EmbedTextType
from shared_configs.enums import RerankerProvider

Embedding = list[float]


class EmbedRequest(BaseModel):
    texts: list[str]
    # Can be none for cloud embedding model requests, error handling logic exists for other cases
    model_name: str | None
    max_context_length: int
    normalize_embeddings: bool
    api_key: str | None
    provider_type: EmbeddingProvider | None
    text_type: EmbedTextType
    manual_query_prefix: str | None
    manual_passage_prefix: str | None


class EmbedResponse(BaseModel):
    embeddings: list[Embedding]


class RerankRequest(BaseModel):
    query: str
    documents: list[str]
    model_name: str
    provider_type: RerankerProvider | None
    api_key: str | None


class RerankResponse(BaseModel):
    scores: list[float]


class IntentRequest(BaseModel):
    query: str
    # Sequence classification threshold
    semantic_percent_threshold: float
    # Token classification threshold
    keyword_percent_threshold: float


class IntentResponse(BaseModel):
    is_keyword: bool
    keywords: list[str]
