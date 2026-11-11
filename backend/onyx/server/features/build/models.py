from uuid import UUID

from pydantic import BaseModel


class UploadResponse(BaseModel):
    """Response after successful file upload."""

    filename: str  # Sanitized filename
    path: str  # Relative path in sandbox (e.g., "attachments/doc.pdf")
    size_bytes: int  # File size in bytes


class BaseInstructionsResponse(BaseModel):
    content: str


class StaticPreviewGrant(BaseModel):
    tenant_id: str
    session_id: UUID
    user_id: UUID
    root: str
    files: dict[str, int]
    revisions: dict[str, str]


class StaticPreviewResponse(BaseModel):
    path: str
    expires_in: int
