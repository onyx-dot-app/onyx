import sys
from datetime import datetime
from enum import Enum
from typing import Any
from typing import cast

from pydantic import BaseModel
from pydantic import model_validator

from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import INDEX_SEPARATOR
from onyx.configs.constants import RETURN_SEPARATOR
from onyx.db.enums import IndexModelStatus
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
    """Base section class with common attributes"""

    link: str | None = None
    text: str | None = None
    image_file_id: str | None = None


class TextSection(Section):
    """Section containing text content"""

    text: str

    def __sizeof__(self) -> int:
        return sys.getsizeof(self.text) + sys.getsizeof(self.link)


class ImageSection(Section):
    """Section containing an image reference"""

    image_file_id: str

    def __sizeof__(self) -> int:
        return sys.getsizeof(self.image_file_id) + sys.getsizeof(self.link)


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

    def get_email(self) -> str | None:
        return self.email or None

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

    def __sizeof__(self) -> int:
        size = sys.getsizeof(self.display_name)
        size += sys.getsizeof(self.first_name)
        size += sys.getsizeof(self.middle_initial)
        size += sys.getsizeof(self.last_name)
        size += sys.getsizeof(self.email)
        return size

    @classmethod
    def from_dict(cls, model_dict: dict[str, Any]) -> "BasicExpertInfo":

        first_name = cast(str, model_dict.get("FirstName"))
        last_name = cast(str, model_dict.get("LastName"))
        email = cast(str, model_dict.get("Email"))
        display_name = cast(str, model_dict.get("Name"))

        # Check if all fields are None
        if (
            first_name is None
            and last_name is None
            and email is None
            and display_name is None
        ):
            raise ValueError("No identifying information found for user")

        return cls(
            first_name=first_name,
            last_name=last_name,
            email=email,
            display_name=display_name,
        )


class DocumentBase(BaseModel):
    """Used for Onyx ingestion api, the ID is inferred before use if not provided"""

    id: str | None = None
    sections: list[TextSection | ImageSection]
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

    # only filled in EE for connectors w/ permission sync enabled
    external_access: ExternalAccess | None = None
    doc_metadata: dict[str, Any] | None = None

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

    def __sizeof__(self) -> int:
        size = sys.getsizeof(self.id)
        for section in self.sections:
            size += sys.getsizeof(section)
        size += sys.getsizeof(self.source)
        size += sys.getsizeof(self.semantic_identifier)
        size += sys.getsizeof(self.doc_updated_at)
        size += sys.getsizeof(self.chunk_count)

        if self.primary_owners is not None:
            for primary_owner in self.primary_owners:
                size += sys.getsizeof(primary_owner)
        else:
            size += sys.getsizeof(self.primary_owners)

        if self.secondary_owners is not None:
            for secondary_owner in self.secondary_owners:
                size += sys.getsizeof(secondary_owner)
        else:
            size += sys.getsizeof(self.secondary_owners)

        size += sys.getsizeof(self.title)
        size += sys.getsizeof(self.from_ingestion_api)
        size += sys.getsizeof(self.additional_info)
        return size

    def get_text_content(self) -> str:
        return " ".join([section.text for section in self.sections if section.text])


class Document(DocumentBase):
    """Used for Onyx ingestion api, the ID is required"""

    id: str
    source: DocumentSource

    def to_short_descriptor(self) -> str:
        """Used when logging the identity of a document"""
        return f"ID: '{self.id}'; Semantic ID: '{self.semantic_identifier}'"

    @classmethod
    def from_base(cls, base: DocumentBase) -> "Document":
        return cls(
            id=(
                make_url_compatible(base.id)
                if base.id
                else "ingestion_api_" + make_url_compatible(base.semantic_identifier)
            ),
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

    def __sizeof__(self) -> int:
        size = super().__sizeof__()
        size += sys.getsizeof(self.id)
        size += sys.getsizeof(self.source)
        return size


class IndexingDocument(Document):
    """Document with processed sections for indexing"""

    processed_sections: list[Section] = []

    def get_total_char_length(self) -> int:
        """Get the total character length of the document including processed sections"""
        title_len = len(self.title or self.semantic_identifier)

        # Use processed_sections if available, otherwise fall back to original sections
        if self.processed_sections:
            section_len = sum(
                len(section.text) if section.text is not None else 0
                for section in self.processed_sections
            )
        else:
            section_len = sum(
                (
                    len(section.text)
                    if isinstance(section, TextSection) and section.text is not None
                    else 0
                )
                for section in self.sections
            )

        return title_len + section_len


class SlimDocument(BaseModel):
    id: str
    external_access: ExternalAccess | None = None


class IndexAttemptMetadata(BaseModel):
    connector_id: int
    credential_id: int
    batch_num: int | None = None
    attempt_id: int | None = None
    request_id: str | None = None

    # Work in progress: will likely contain metadata about cc pair / index attempt
    structured_id: str | None = None


class ConnectorCheckpoint(BaseModel):
    # TODO: maybe move this to something disk-based to handle extremely large checkpoints?
    has_more: bool

    def __str__(self) -> str:
        """String representation of the checkpoint, with truncation for large checkpoint content."""
        MAX_CHECKPOINT_CONTENT_CHARS = 1000

        content_str = self.model_dump_json()
        if len(content_str) > MAX_CHECKPOINT_CONTENT_CHARS:
            content_str = content_str[: MAX_CHECKPOINT_CONTENT_CHARS - 3] + "..."
        return content_str


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


class ConnectorStopSignal(Exception):
    """A custom exception used to signal a stop in processing."""


class OnyxMetadata(BaseModel):
    # Note that doc_id cannot be overriden here as it may cause issues
    # with the display functionalities in the UI. Ask @chris if clarification is needed.
    source_type: DocumentSource | None = None
    link: str | None = None
    file_display_name: str | None = None
    primary_owners: list[BasicExpertInfo] | None = None
    secondary_owners: list[BasicExpertInfo] | None = None
    doc_updated_at: datetime | None = None
    title: str | None = None


class DocExtractionContext(BaseModel):
    index_name: str
    cc_pair_id: int
    connector_id: int
    credential_id: int
    source: DocumentSource
    earliest_index_time: float
    from_beginning: bool
    is_primary: bool
    should_fetch_permissions_during_indexing: bool
    search_settings_status: IndexModelStatus
    doc_extraction_complete_batch_num: int | None


class DocIndexingContext(BaseModel):
    batches_done: int
    total_failures: int
    net_doc_change: int
    total_chunks: int
