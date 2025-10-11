from pydantic import BaseModel


class QdrantSearchRequest(BaseModel):
    query: str
    limit: int = 10


class QdrantSearchResult(BaseModel):
    document_id: str
    content: str
    filename: str | None
    source_type: str | None
    score: float
    metadata: dict | None


class QdrantSearchResponse(BaseModel):
    results: list[QdrantSearchResult]
    query: str
    total_results: int
