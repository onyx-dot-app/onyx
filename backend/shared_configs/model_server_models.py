from pydantic import BaseModel


class EmbedRequest(BaseModel):
    # This already includes any prefixes, the text is just passed directly to the model
    texts: list[str]
    model_name: str
    max_context_length: int
    normalize_embeddings: bool


class EmbedResponse(BaseModel):
    embeddings: list[list[float]]


class RerankRequest(BaseModel):
    query: str
    documents: list[str]


class RerankResponse(BaseModel):
    scores: list[list[float]]


class IntentRequest(BaseModel):
    query: str


class IntentResponse(BaseModel):
    class_probs: list[float]
