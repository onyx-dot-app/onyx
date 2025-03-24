from collections import defaultdict
from typing import Dict

from pydantic import BaseModel


class KGChunkFormat(BaseModel):
    connector_id: int | None = None
    document_id: str
    chunk_id: int
    title: str
    content: str
    primary_owners: list[str]
    secondary_owners: list[str]
    source_type: str
    metadata: dict[str, str | list[str]] | None = None
    entities: Dict[str, int] = {}
    relationships: Dict[str, int] = {}
    terms: Dict[str, int] = {}


class KGChunkExtraction(BaseModel):
    connector_id: int
    document_id: str
    chunk_id: int
    entities: list[str]
    relationships: list[str]
    terms: list[str]


class KGChunkId(BaseModel):
    connector_id: int | None = None
    document_id: str
    chunk_id: int


class KGAggregatedExtractions(BaseModel):
    entities: defaultdict[str, int]
    relationships: defaultdict[str, int]
    terms: defaultdict[str, int]


class KGBatchExtractionStats(BaseModel):
    connector_id: int | None = None
    succeeded: list[KGChunkId]
    failed: list[KGChunkId]
    aggregated_kg_extractions: KGAggregatedExtractions


class ConnectorExtractionStats(BaseModel):
    connector_id: int
    num_succeeded: int
    num_failed: int
    num_processed: int


class KGPerson(BaseModel):
    name: str
    company: str
    employee: bool
