from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel
from pydantic import model_validator

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import INDEX_SEPARATOR
from onyx.configs.constants import RETURN_SEPARATOR
from onyx.utils.text_processing import make_url_compatible


class InputType(str, Enum):
    LOAD_STATE = "load_state"  # e.g. loading a current full state or a save state, such as from a file
    POLL = "poll"  # e.g. calling an API to get all documents in the last hour
    EVENT = "event"  # e.g. registered an endpoint as a listener, and processing connector events
    SLIM_RETRIEVAL = "slim_retrieval"


class ConnectorMissingCredentialError(PermissionError):
    def __init__(self, connector_name: str) -> None:
        connector_name = connector_name or "Unknown"
        super().__init__(
            f"{connector_name} connector missing credentials, was load_credentials called?"
        )


class Section(BaseModel):
    text: str
    link: str | None


class BasicExpertInfo(BaseModel):
    """Basic Information for the owner of a document, any of the fields can be left as None
    Display fallback goes as follows:
    - first_name + (optional middle_initial) + last_name
    - display_name
    - email
    - first_name
    """

    display_name: str | None = None
    first_name: str | None = None
    middle_initial: str | None = None
    last_name: str | None = None
    email: str | None = None

    def get_semantic_name(self) -> str:
        if self.first_name and self.last_name:
            name_parts = [self.first_name]
            if self.middle_initial:
                name_parts.append(self.middle_initial + ".")
            name_parts.append(self.last_name)
            return " ".join([name_part.capitalize() for name_part in name_parts])

        if self.display_name:
            return self.display_name

        if self.email:
            return self.email

        if self.first_name:
            return self.first_name.capitalize()

        return "Unknown"

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, BasicExpertInfo):
            return False
        return (
            self.display_name,
            self.first_name,
            self.middle_initial,
            self.last_name,
            self.email,
        ) == (
            other.display_name,
            other.first_name,
            other.middle_initial,
            other.last_name,
            other.email,
        )

    def __hash__(self) -> int:
        return hash(
            (
                self.display_name,
                self.first_name,
                self.middle_initial,
                self.last_name,
                self.email,
            )
        )


class DocumentBase(BaseModel):
    """Used for Onyx ingestion api, the ID is inferred before use if not provided"""

    id: str | None = None
    sections: list[Section]
    source: DocumentSource | None = None
    semantic_identifier: str  # displayed in the UI as the main identifier for the doc
    metadata: dict[str, str | list[str]]

    # UTC time
    doc_updated_at: datetime | None = None
    chunk_count: int | None = None

    # Owner, creator, etc.
    primary_owners: list[BasicExpertInfo] | None = None
    # Assignee, space owner, etc.
    secondary_owners: list[BasicExpertInfo] | None = None
    # title is used for search whereas semantic_identifier is used for displaying in the UI
    # different because Slack message may display as #general but general should not be part
    # of the search, at least not in the same way as a document title should be for like Confluence
    # The default title is semantic_identifier though unless otherwise specified
    title: str | None = None
    from_ingestion_api: bool = False
    # Anything else that may be useful that is specific to this particular connector type that other
    # parts of the code may need. If you're unsure, this can be left as None
    additional_info: Any = None

    def get_title_for_document_index(
        self,
    ) -> str | None:
        # If title is explicitly empty, return a None here for embedding purposes
        if self.title == "":
            return None
        replace_chars = set(RETURN_SEPARATOR)
        title = self.semantic_identifier if self.title is None else self.title
        for char in replace_chars:
            title = title.replace(char, " ")
        title = title.strip()
        return title

    def get_metadata_str_attributes(self) -> list[str] | None:
        if not self.metadata:
            return None
        # Combined string for the key/value for easy filtering
        attributes: list[str] = []
        for k, v in self.metadata.items():
            if isinstance(v, list):
                attributes.extend([k + INDEX_SEPARATOR + vi for vi in v])
            else:
                attributes.append(k + INDEX_SEPARATOR + v)
        return attributes


class Document(DocumentBase):
    id: str  # This must be unique or during indexing/reindexing, chunks will be overwritten
    source: DocumentSource

    def get_total_char_length(self) -> int:
        """Calculate the total character length of the document including sections, metadata, and identifiers."""
        section_length = sum(len(section.text) for section in self.sections)
        identifier_length = len(self.semantic_identifier) + len(self.title or "")
        metadata_length = sum(
            len(k) + len(v) if isinstance(v, str) else len(k) + sum(len(x) for x in v)
            for k, v in self.metadata.items()
        )
        return section_length + identifier_length + metadata_length

    def to_short_descriptor(self) -> str:
        """Used when logging the identity of a document"""
        return f"ID: '{self.id}'; Semantic ID: '{self.semantic_identifier}'"

    @classmethod
    def from_base(cls, base: DocumentBase) -> "Document":
        return cls(
            id=make_url_compatible(base.id)
            if base.id
            else "ingestion_api_" + make_url_compatible(base.semantic_identifier),
            sections=base.sections,
            source=base.source or DocumentSource.INGESTION_API,
            semantic_identifier=base.semantic_identifier,
            metadata=base.metadata,
            doc_updated_at=base.doc_updated_at,
            primary_owners=base.primary_owners,
            secondary_owners=base.secondary_owners,
            title=base.title,
            from_ingestion_api=base.from_ingestion_api,
        )


class SlimDocument(BaseModel):
    id: str
    perm_sync_data: Any | None = None


class IndexAttemptMetadata(BaseModel):
    batch_num: int | None = None
    connector_id: int
    credential_id: int


class ConnectorCheckpoint(BaseModel):
    # TODO: maybe move this to something disk-based to handle extremely large checkpoints?
    checkpoint_content: dict
    has_more: bool

    @classmethod
    def build_dummy_checkpoint(cls) -> "ConnectorCheckpoint":
        return ConnectorCheckpoint(checkpoint_content={}, has_more=True)


class DocumentFailure(BaseModel):
    document_id: str
    document_link: str | None = None


class EntityFailure(BaseModel):
    entity_id: str
    missed_time_range: tuple[datetime, datetime] | None = None


class ConnectorFailure(BaseModel):
    failed_document: DocumentFailure | None = None
    failed_entity: EntityFailure | None = None
    failure_message: str
    exception: Exception | None = None

    model_config = {"arbitrary_types_allowed": True}

    @model_validator(mode="before")
    def check_failed_fields(cls, values: dict) -> dict:
        failed_document = values.get("failed_document")
        failed_entity = values.get("failed_entity")
        if (failed_document is None and failed_entity is None) or (
            failed_document is not None and failed_entity is not None
        ):
            raise ValueError(
                "Exactly one of 'failed_document' or 'failed_entity' must be specified."
            )
        return values
