from datetime import datetime

from pydantic import BaseModel

from onyx.configs.constants import MessageType
from onyx.db.enums import ArtifactType
from onyx.db.enums import BuildSessionStatus
from onyx.db.enums import SandboxStatus


# ===== Session Models =====
class SessionCreateRequest(BaseModel):
    """Request to create a new build session."""

    name: str | None = None  # Optional session name


class SessionUpdateRequest(BaseModel):
    """Request to update a build session."""

    name: str | None = None


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
    session_id: str
    type: ArtifactType
    name: str
    path: str
    preview_url: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, artifact) -> "ArtifactResponse":
        """Convert Artifact ORM model to response."""
        return cls(
            id=str(artifact.id),
            session_id=str(artifact.session_id),
            type=artifact.type,
            name=artifact.name,
            path=artifact.path,
            preview_url=getattr(artifact, "preview_url", None),
            created_at=artifact.created_at,
            updated_at=artifact.updated_at,
        )


class SessionResponse(BaseModel):
    """Response containing session details."""

    id: str
    user_id: str | None
    name: str | None
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
            name=session.name,
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


# ===== Message Models =====
class MessageRequest(BaseModel):
    """Request to send a message to the CLI agent."""

    content: str


class MessageResponse(BaseModel):
    """Response containing message details."""

    id: str
    session_id: str
    type: MessageType
    content: str
    created_at: datetime

    @classmethod
    def from_model(cls, message):
        """Convert BuildMessage ORM model to response."""
        return cls(
            id=str(message.id),
            session_id=str(message.session_id),
            type=message.type,
            content=message.content,
            created_at=message.created_at,
        )


class MessageListResponse(BaseModel):
    """Response containing list of messages."""

    messages: list[MessageResponse]


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
