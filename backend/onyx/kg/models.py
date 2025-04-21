from enum import Enum
from typing import Any
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
    deep_extraction: bool = False


class KGChunkExtraction(BaseModel):
    connector_id: int
    document_id: str
    chunk_id: int
    core_entity: str
    entities: list[str]
    relationships: list[str]
    terms: list[str]


class KGChunkId(BaseModel):
    connector_id: int | None = None
    document_id: str
    chunk_id: int


class KGRelationshipExtraction(BaseModel):
    relationship_str: str
    source_document_id: str


class KGAggregatedExtractions(BaseModel):
    grounded_entities_document_ids: dict[str, str]
    entities: dict[str, int]
    relationships: dict[str, dict[str, int]]
    terms: dict[str, int]


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


class NormalizedEntities(BaseModel):
    entities: list[str]
    entity_normalization_map: dict[str, str | None]


class NormalizedRelationships(BaseModel):
    relationships: list[str]
    relationship_normalization_map: dict[str, str | None]


class NormalizedTerms(BaseModel):
    terms: list[str]
    term_normalization_map: dict[str, str | None]


class KGClassificationContent(BaseModel):
    document_id: str
    classification_content: str
    source_type: str
    source_metadata: dict[str, Any] | None = None


class KGClassificationDecisions(BaseModel):
    document_id: str
    classification_decision: bool
    classification_class: str | None
    source_metadata: dict[str, Any] | None = None


class KGClassificationRule(BaseModel):
    description: str
    extration: bool


class KGClassificationInstructionStrings(BaseModel):
    classification_options: str
    classification_class_definitions: dict[str, Dict[str, str | bool]]


class KGExtractionInstructions(BaseModel):
    deep_extraction: bool
    active: bool


class KGEntityTypeInstructions(BaseModel):
    classification_instructions: KGClassificationInstructionStrings
    extraction_instructions: KGExtractionInstructions


class ContextPreparation(BaseModel):
    """
    Context preparation format for the LLM KG extraction.
    """

    llm_context: str
    core_entity: str
    implied_entities: list[str]
    implied_relationships: list[str]
    implied_terms: list[str]


class KGDocumentClassificationPrompt(BaseModel):
    """
    Document classification prompt format for the LLM KG extraction.
    """

    llm_prompt: str | None


class KGConnectorData(BaseModel):
    id: int
    source: str


class KGStage(str, Enum):
    EXTRACTED = "extracted"
    NORMALIZED = "normalized"
    FAILED = "failed"
    SKIPPED = "skipped"
    EXTRACTION_READY = "extraction_ready"
