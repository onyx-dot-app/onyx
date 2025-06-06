from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel

from onyx.configs.kg_configs import KG_DEFAULT_MAX_PARENT_RECURSION_DEPTH


class KGConfigSettings(BaseModel):
    KG_EXPOSED: bool = False
    KG_ENABLED: bool = False
    KG_VENDOR: str | None = None
    KG_VENDOR_DOMAINS: list[str] | None = None
    KG_IGNORE_EMAIL_DOMAINS: list[str] | None = None
    KG_EXTRACTION_IN_PROGRESS: bool = False
    KG_CLUSTERING_IN_PROGRESS: bool = False
    KG_COVERAGE_START: datetime = datetime(1970, 1, 1)
    KG_MAX_COVERAGE_DAYS: int = 10000
    KG_MAX_PARENT_RECURSION_DEPTH: int = KG_DEFAULT_MAX_PARENT_RECURSION_DEPTH


class KGConfigVars(str, Enum):
    KG_EXPOSED = "KG_EXPOSED"
    KG_ENABLED = "KG_ENABLED"
    KG_VENDOR = "KG_VENDOR"
    KG_VENDOR_DOMAINS = "KG_VENDOR_DOMAINS"
    KG_IGNORE_EMAIL_DOMAINS = "KG_IGNORE_EMAIL_DOMAINS"
    KG_EXTRACTION_IN_PROGRESS = "KG_EXTRACTION_IN_PROGRESS"
    KG_CLUSTERING_IN_PROGRESS = "KG_CLUSTERING_IN_PROGRESS"
    KG_COVERAGE_START = "KG_COVERAGE_START"
    KG_MAX_COVERAGE_DAYS = "KG_MAX_COVERAGE_DAYS"
    KG_MAX_PARENT_RECURSION_DEPTH = "KG_MAX_PARENT_RECURSION_DEPTH"


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
    entities: dict[str, int] = {}
    relationships: dict[str, int] = {}
    terms: dict[str, int] = {}
    deep_extraction: bool = False


class KGChunkExtraction(BaseModel):
    connector_id: int
    document_id: str
    chunk_id: int
    core_entity: str
    entities: list[str]
    relationships: list[str]
    terms: list[str]
    attributes: dict[str, str | list[str]]


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
    attributes: dict[str, dict[str, str | list[str]]]


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
    entity_normalization_map: dict[str, str]


class NormalizedRelationships(BaseModel):
    relationships: list[str]
    relationship_normalization_map: dict[str, str]


class NormalizedTerms(BaseModel):
    terms: list[str]
    term_normalization_map: dict[str, str | None]


class KGClassificationContent(BaseModel):
    document_id: str
    classification_content: str
    source_type: str
    source_metadata: dict[str, Any] | None = None
    entity_type: str | None = None
    metadata: dict[str, Any] | None = None


class KGEnrichedClassificationContent(KGClassificationContent):
    classification_enabled: bool
    classification_instructions: dict[str, Any]
    deep_extraction: bool


class KGClassificationDecisions(BaseModel):
    document_id: str
    classification_decision: bool
    classification_class: str | None
    source_metadata: dict[str, Any] | None = None


class KGClassificationInstructions(BaseModel):
    classification_enabled: bool
    classification_options: str
    classification_class_definitions: dict[str, dict[str, str | bool]]


class KGExtractionInstructions(BaseModel):
    deep_extraction: bool
    active: bool


class KGEntityTypeInstructions(BaseModel):
    classification_instructions: KGClassificationInstructions
    extraction_instructions: KGExtractionInstructions
    filter_instructions: dict[str, Any] | None = None


class KGEnhancedDocumentMetadata(BaseModel):
    entity_type: str | None
    document_attributes: dict[str, Any] | None
    deep_extraction: bool
    classification_enabled: bool
    classification_instructions: KGClassificationInstructions | None
    skip: bool


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
    kg_coverage_days: int | None


class KGStage(str, Enum):
    EXTRACTED = "extracted"
    NORMALIZED = "normalized"
    FAILED = "failed"
    SKIPPED = "skipped"
    NOT_STARTED = "not_started"
    EXTRACTING = "extracting"
    DO_NOT_EXTRACT = "do_not_extract"


class KGDocumentEntitiesRelationshipsAttributes(BaseModel):
    kg_core_document_id_name: str
    implied_entities: set[str]
    implied_relationships: set[str]
    converted_relationships_to_attributes: dict[str, list[str]]
    company_participant_emails: set[str]
    account_participant_emails: set[str]
    converted_attributes_to_relationships: set[str]
    document_attributes: dict[str, Any] | None


class KGGroundingType(str, Enum):
    UNGROUNDED = "ungrounded"
    GROUNDED = "grounded"


class KGDefaultEntityDefinition(BaseModel):
    description: str
    grounding: KGGroundingType
    active: bool = False
    grounded_source_name: str | None
    attributes: dict = {}
    entity_values: dict = {}


class MetadataTrackType(str, Enum):
    VALUE = "value"
    LIST = "list"


class MetadataTrackInfo(BaseModel):
    type: MetadataTrackType
    values: set[str] | None
