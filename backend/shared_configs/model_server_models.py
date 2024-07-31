from pydantic import BaseModel

from shared_configs.enums import EmbedTextType

Embedding = list[float]


class EmbedRequest(BaseModel):
    texts: list[str]
    # Can be none for cloud embedding model requests, error handling logic exists for other cases
    model_name: str | None
    max_context_length: int
    normalize_embeddings: bool
    api_key: str | None
    provider_type: str | None
    text_type: EmbedTextType
    manual_query_prefix: str | None
    manual_passage_prefix: str | None


class EmbedResponse(BaseModel):
    embeddings: list[Embedding]


class RerankRequest(BaseModel):
    query: str
    documents: list[str]


class RerankResponse(BaseModel):
    scores: list[list[float] | None]


class IntentRequest(BaseModel):
    query: str


class IntentResponse(BaseModel):
    class_probs: list[float]
