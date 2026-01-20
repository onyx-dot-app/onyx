from datetime import datetime

from pydantic import BaseModel

from onyx.db.enums import ArtifactType
from onyx.db.enums import BuildSessionStatus
from onyx.db.enums import SandboxStatus


# ===== Session Models =====
class SessionCreateRequest(BaseModel):
    """Request to create a new build session."""

    pass  # No fields required - session is created empty


class SandboxResponse(BaseModel):
    """Sandbox metadata in session response."""

    id: str
    status: SandboxStatus
    container_id: str | None
    created_at: datetime
    last_heartbeat: datetime | None

    @classmethod
    def from_model(cls, sandbox) -> "SandboxResponse":
        """Convert Sandbox ORM model to response."""
        return cls(
            id=str(sandbox.id),
            status=sandbox.status,
            container_id=sandbox.container_id,
            created_at=sandbox.created_at,
            last_heartbeat=sandbox.last_heartbeat,
        )


class ArtifactResponse(BaseModel):
    """Artifact metadata in session response."""

    id: str
    type: ArtifactType
    name: str
    path: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, artifact) -> "ArtifactResponse":
        """Convert Artifact ORM model to response."""
        return cls(
            id=str(artifact.id),
            type=artifact.type,
            name=artifact.name,
            path=artifact.path,
            created_at=artifact.created_at,
            updated_at=artifact.updated_at,
        )


class SessionResponse(BaseModel):
    """Response containing session details."""

    id: str
    user_id: str | None
    status: BuildSessionStatus
    created_at: datetime
    last_activity_at: datetime
    sandbox: SandboxResponse | None
    artifacts: list[ArtifactResponse]

    @classmethod
    def from_model(cls, session) -> "SessionResponse":
        """Convert BuildSession ORM model to response."""
        return cls(
            id=str(session.id),
            user_id=str(session.user_id) if session.user_id else None,
            status=session.status,
            created_at=session.created_at,
            last_activity_at=session.last_activity_at,
            sandbox=(
                SandboxResponse.from_model(session.sandbox) if session.sandbox else None
            ),
            artifacts=[ArtifactResponse.from_model(a) for a in session.artifacts],
        )


class SessionListResponse(BaseModel):
    """Response containing list of sessions."""

    sessions: list[SessionResponse]


# ===== Legacy Models (for compatibility with other code) =====
class CreateSessionRequest(BaseModel):
    task: str
    available_sources: list[str] | None = None


class CreateSessionResponse(BaseModel):
    session_id: str


class ExecuteRequest(BaseModel):
    task: str
    context: str | None = None


class ArtifactInfo(BaseModel):
    artifact_type: str  # "webapp", "file", "markdown", "image"
    path: str
    filename: str
    mime_type: str | None = None


class SessionStatus(BaseModel):
    session_id: str
    status: str  # "idle", "running", "completed", "failed"
    webapp_url: str | None = None


class FileSystemEntry(BaseModel):
    name: str  # File/folder name
    path: str  # Relative path from sandbox root
    is_directory: bool  # True for folders
    size: int | None = None  # File size in bytes
    mime_type: str | None = None  # MIME type for files


class DirectoryListing(BaseModel):
    path: str  # Current directory path
    entries: list[FileSystemEntry]  # Contents
