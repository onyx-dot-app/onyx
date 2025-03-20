from pydantic import BaseModel


class KGChunkFormat(BaseModel):
    connector_id: int | None = None
    document_id: str
    chunk_id: int
    title: str
    content: str
    metadata: dict[str, str | list[str]] | None = None


class KGChunkExtraction(BaseModel):
    connector_id: int
    document_id: str
    entities: list[str]
    relationships: list[str]
    terms: list[str]


class KGChunkId(BaseModel):
    connector_id: int | None = None
    document_id: str
    chunk_id: int


class KGChunkExtractionStats(BaseModel):
    connector_id: int | None = None
    succeeded: list[KGChunkId]
    failed: list[KGChunkId]


class ConnectorExtractionStats(BaseModel):
    connector_id: int
    num_succeeded: int
    num_failed: int
