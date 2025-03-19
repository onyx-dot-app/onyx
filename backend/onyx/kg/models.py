from pydantic import BaseModel


class KGChunk(BaseModel):
    connector_id: str
    document_id: str
    chunk_id: int
    title: str
    content: str
    metadata: dict[str, str | list[str]]


class KGChunkExtraction(BaseModel):
    connector_id: str
    document_id: str
    entities: list[str]
    relationships: list[str]
    terms: list[str]
