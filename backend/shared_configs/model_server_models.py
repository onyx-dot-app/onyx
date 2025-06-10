from pydantic import BaseModel

from shared_configs.enums import EmbeddingProvider
from shared_configs.enums import EmbedTextType
from shared_configs.enums import RerankerProvider


Embedding = list[float]


class ConnectorClassificationRequest(BaseModel):
    available_connectors: list[str]
    query: str


class ConnectorClassificationResponse(BaseModel):
    connectors: list[str]


class EmbedRequest(BaseModel):
    texts: list[str]
    # Can be none for cloud embedding model requests, error handling logic exists for other cases
    model_name: str | None = None
    deployment_name: str | None = None
    max_context_length: int
    normalize_embeddings: bool
    api_key: str | None = None
    provider_type: EmbeddingProvider | None = None
    text_type: EmbedTextType
    manual_query_prefix: str | None = None
    manual_passage_prefix: str | None = None
    api_url: str | None = None
    api_version: str | None = None

    # allows for the truncation of the vector to a lower dimension
    # to reduce memory usage. Currently only supported for OpenAI models.
    # will be ignored for other providers.
    reduced_dimension: int | None = None

    # This disables the "model_" protected namespace for pydantic
    model_config = {"protected_namespaces": ()}


class EmbedResponse(BaseModel):
    embeddings: list[Embedding]


class RerankRequest(BaseModel):
    query: str
    documents: list[str]
    model_name: str
    provider_type: RerankerProvider | None = None
    api_key: str | None = None
    api_url: str | None = None

    # This disables the "model_" protected namespace for pydantic
    model_config = {"protected_namespaces": ()}


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


class InformationContentClassificationRequests(BaseModel):
    queries: list[str]


class ContentClassificationPrediction(BaseModel):
    predicted_label: int
    content_boost_factor: float


class InformationContentClassificationResponses(BaseModel):
    information_content_classifications: list[ContentClassificationPrediction]
