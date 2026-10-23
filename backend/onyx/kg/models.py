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


class KGGroundingType(str, Enum):
    UNGROUNDED = "ungrounded"
    GROUNDED = "grounded"


class KGAttributeTrackType(str, Enum):
    VALUE = "value"
    LIST = "list"


class KGAttributeTrackInfo(BaseModel):
    type: KGAttributeTrackType
    values: set[str] | None


class KGAttributeEntityOption(str, Enum):
    FROM_EMAIL = "from_email"  # use email to determine type (ACCOUNT or EMPLOYEE)


class KGAttributeImplicationProperty(BaseModel):
    # type of implied entity to create
    # if str, will create an implied entity of that type
    # if KGAttributeEntityOption, will determine the type based on the option
    implied_entity_type: str | KGAttributeEntityOption
    # name of the implied relationship to create (from implied entity to this entity)
    implied_relationship_name: str


class KGAttributeProperty(BaseModel):
    # name of attribute to map metadata to
    name: str
    # whether to keep this attribute in the entity
    keep: bool
    # properties for creating implied entities and relations from this metadata
    implication_property: KGAttributeImplicationProperty | None = None


class KGEntityTypeClassificationInfo(BaseModel):
    extraction: bool
    description: str


class KGEntityTypeAttributes(BaseModel):
    # information on how to use the metadata to extract attributes, implied entities, and relations
    metadata_attribute_conversion: dict[str, KGAttributeProperty] = {}
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


class KGStage(str, Enum):
    EXTRACTED = "extracted"
    NORMALIZED = "normalized"
    FAILED = "failed"
    SKIPPED = "skipped"
    NOT_STARTED = "not_started"
    EXTRACTING = "extracting"
    DO_NOT_EXTRACT = "do_not_extract"
