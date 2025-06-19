from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel

from onyx.configs.constants import DocumentSource
from onyx.configs.kg_configs import KG_DEFAULT_MAX_PARENT_RECURSION_DEPTH


# Note: make sure to write a migration if adding a non-nullable field or removing a field
class KGConfigSettings(BaseModel):
    KG_EXPOSED: bool = False
    KG_ENABLED: bool = False
    KG_VENDOR: str | None = None
    KG_VENDOR_DOMAINS: list[str] = []
    KG_IGNORE_EMAIL_DOMAINS: list[str] = []
    KG_COVERAGE_START: str = datetime(1970, 1, 1).strftime("%Y-%m-%d")
    KG_MAX_COVERAGE_DAYS: int = 10000
    KG_MAX_PARENT_RECURSION_DEPTH: int = KG_DEFAULT_MAX_PARENT_RECURSION_DEPTH
    KG_BETA_PERSONA_ID: int | None = None

    @property
    def KG_COVERAGE_START_DATE(self) -> datetime:
        return datetime.strptime(self.KG_COVERAGE_START, "%Y-%m-%d")


class KGProcessingStatus(BaseModel):
    in_progress: bool = False


class KGGroundingType(str, Enum):
    UNGROUNDED = "ungrounded"
    GROUNDED = "grounded"


class KGAttributeTrackType(str, Enum):
    VALUE = "value"
    LIST = "list"


class KGAttributeTrackInfo(BaseModel):
    type: KGAttributeTrackType
    values: set[str] | None


class KGEntityTypeClassificationInfo(BaseModel):
    extraction: bool
    description: str


class KGEntityTypeAttributes(BaseModel):
    # mapping of metadata keys to their corresponding attribute names
    # there are several special attributes that you can map to:
    # - key: used to populate the entity_key field of the kg entity
    # - parent: used to populate the parent_key field of the kg entity
    # - subtype: special attribute that can be filtered for
    metadata_attributes: dict[str, str] = {}
    # a metadata key: value pair to match for to differentiate entities from the same source
    entity_filter_attributes: dict[str, Any] = {}
    # mapping of classification names to their corresponding classification info
    classification_attributes: dict[str, KGEntityTypeClassificationInfo] = {}

    # mapping of attribute names to their allowed values, populated during extraction
    attribute_values: dict[str, KGAttributeTrackInfo | None] = {}


class KGEntityTypeDefinition(BaseModel):
    description: str
    grounding: KGGroundingType
    grounded_source_name: DocumentSource | None
    active: bool = False
    attributes: KGEntityTypeAttributes = KGEntityTypeAttributes()
    entity_values: list[str] = []


class KGChunkRelationship(BaseModel):
    source: str
    rel_type: str
    target: str


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
    entities: list[str] = []
    relationships: list[KGChunkRelationship] = []
    terms: list[str] = []
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
    entities_w_attributes: list[str]
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
    classification_class_definitions: dict[str, KGEntityTypeClassificationInfo]


class KGExtractionInstructions(BaseModel):
    deep_extraction: bool
    active: bool


class KGEntityTypeInstructions(BaseModel):
    metadata_attribute_conversion: dict[str, str]
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


class KGException(Exception):
    pass
