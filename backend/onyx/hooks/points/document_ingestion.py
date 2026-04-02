from pydantic import BaseModel
from pydantic import Field

from onyx.db.enums import HookFailStrategy
from onyx.db.enums import HookPoint
from onyx.hooks.points.base import HookPointSpec


class DocumentIngestionSection(BaseModel):
    """Represents a single section of a document — either text or image, not both.

    Text section: set `text`, leave `image_file_id` null.
    Image section: set `image_file_id`, leave `text` null.
    """

    text: str | None = Field(
        default=None,
        description="Text content of this section. Set for text sections, null for image sections.",
    )
    link: str | None = Field(
        default=None,
        description="Optional URL associated with this section. Preserve the original link from the payload if you want it retained.",
    )
    image_file_id: str | None = Field(
        default=None,
        description=(
            "Opaque identifier for an image stored in the file store. "
            "The image content is not included — this field signals that the section is an image. "
            "Hooks can use its presence to reorder or drop image sections, but cannot read or modify the image itself."
        ),
    )


class DocumentIngestionOwner(BaseModel):
    display_name: str | None = Field(
        default=None,
        description="Human-readable name of the owner.",
    )
    email: str | None = Field(
        default=None,
        description="Email address of the owner.",
    )


class DocumentIngestionPayload(BaseModel):
    document_id: str = Field(
        description="Unique identifier for the document. Read-only — changes are ignored."
    )
    title: str | None = Field(description="Title of the document.")
    semantic_identifier: str = Field(
        description="Human-readable identifier used for display (e.g. file name, page title)."
    )
    source: str = Field(
        description=(
            "Connector source type (e.g. confluence, slack, google_drive). "
            "Read-only — changes are ignored. "
            "Full list of values: https://github.com/onyx-dot-app/onyx/blob/main/backend/onyx/configs/constants.py#L195"
        )
    )
    sections: list[DocumentIngestionSection] = Field(
        description="Sections of the document. Includes both text sections (text set, image_file_id null) and image sections (image_file_id set, text null)."
    )
    metadata: dict[str, list[str]] = Field(
        description="Key-value metadata attached to the document. Values are always a list of strings."
    )
    doc_updated_at: str | None = Field(
        description="ISO 8601 UTC timestamp of the last update at the source, or null if unknown. Example: '2024-03-15T10:30:00+00:00'."
    )
    primary_owners: list[DocumentIngestionOwner] | None = Field(
        description="Primary owners of the document, or null if not available."
    )
    secondary_owners: list[DocumentIngestionOwner] | None = Field(
        description="Secondary owners of the document, or null if not available."
    )


class DocumentIngestionResponse(BaseModel):
    # Intentionally permissive — customer endpoints may return extra fields.
    sections: list[DocumentIngestionSection] | None = Field(
        description="The sections to index, in the desired order. Reorder, drop, or modify sections freely. Null or empty list drops the document."
    )
    rejection_reason: str | None = Field(
        default=None,
        description="Logged when sections is null or empty. Falls back to a generic message if omitted.",
    )


class DocumentIngestionSpec(HookPointSpec):
    """Hook point that runs on every document before it enters the indexing pipeline.

    Call site: immediately after Onyx's internal validation and before the
    indexing pipeline begins — no partial writes have occurred yet.

    If a Document Ingestion hook is configured, it takes precedence —
    Document Ingestion Light will not run. Configure only one per deployment.

    Supported use cases:
    - Document filtering: drop documents based on content or metadata
    - Content rewriting: redact PII or normalize text before indexing
    """

    hook_point = HookPoint.DOCUMENT_INGESTION
    display_name = "Document Ingestion"
    description = (
        "Runs on every document before it enters the indexing pipeline. "
        "Allows filtering, rewriting, or dropping documents."
    )
    default_timeout_seconds = 30.0
    fail_hard_description = "The document will not be indexed."
    default_fail_strategy = HookFailStrategy.HARD
    docs_url = "https://docs.onyx.app/admins/advanced_configs/hook_extensions#document-ingestion"

    payload_model = DocumentIngestionPayload
    response_model = DocumentIngestionResponse
