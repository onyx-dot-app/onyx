from pydantic import BaseModel
from pydantic import Field

from onyx.db.enums import HookFailStrategy
from onyx.db.enums import HookPoint
from onyx.hooks.points.base import HookPointSpec


class DocumentPushPayload(BaseModel):
    """Payload sent to a Document Push hook endpoint after a document is indexed.

    Unlike Document Ingestion (which fires before indexing and can modify content),
    this hook fires after successful indexing and is fire-and-forget — the response
    is not used to alter the document or pipeline behavior.
    """

    document_id: str = Field(description="Unique identifier for the document.")
    title: str | None = Field(description="Title of the document.")
    content: str = Field(
        description="Full text content of the document (all text sections concatenated)."
    )
    source: str = Field(
        description=(
            "Connector source type (e.g. confluence, slack, google_drive). "
            "Full list: https://github.com/onyx-dot-app/onyx/blob/main/backend/onyx/configs/constants.py#L195"
        )
    )
    url: str | None = Field(
        description="Canonical URL of the document at its source, if available."
    )
    doc_updated_at: str | None = Field(
        description="ISO 8601 UTC timestamp of the last update at the source, or null if unknown."
    )
    metadata: dict[str, list[str]] = Field(
        description="Key-value metadata attached to the document. Values are always a list of strings."
    )


class DocumentPushResponse(BaseModel):
    """Response from a Document Push hook endpoint. The body is not used — any 2xx
    response is treated as success. This model exists only to satisfy the hook
    framework's type requirements."""


class DocumentPushSpec(HookPointSpec):
    """Hook point that fires after a document is successfully indexed.

    Call site: immediately after the document is written to the index, before
    the next document in the batch. Runs only for public connectors in
    single-tenant deployments.

    This hook is fire-and-forget — the response body is ignored. Use it to
    push indexed documents to an external system (e.g. a wiki, data warehouse,
    or audit log).
    """

    hook_point = HookPoint.DOCUMENT_PUSH
    display_name = "Document Push"
    description = (
        "Fires after each document is successfully indexed. "
        "Push indexed documents to an external destination such as a wiki or data warehouse. "
        "Only fires for public connectors in single-tenant deployments."
    )
    default_timeout_seconds = 30.0
    fail_hard_description = "The indexing batch will fail."
    default_fail_strategy = HookFailStrategy.SOFT
    docs_url = (
        "https://docs.onyx.app/admins/advanced_configs/hook_extensions#document-push"
    )

    payload_model = DocumentPushPayload
    response_model = DocumentPushResponse
