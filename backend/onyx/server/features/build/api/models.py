from datetime import datetime
from enum import Enum
from typing import Any
from typing import TYPE_CHECKING
from typing import Union

from pydantic import BaseModel

from onyx.configs.constants import MessageType
from onyx.db.enums import ArtifactType
from onyx.db.enums import BuildSessionStatus
from onyx.db.enums import SandboxStatus
from onyx.server.features.build.sandbox.models import (
    FilesystemEntry as FileSystemEntry,
)

if TYPE_CHECKING:
    from onyx.db.models import Sandbox
    from onyx.db.models import BuildSession


# ===== Session Models =====
class SessionCreateRequest(BaseModel):
    """Request to create a new build session."""

    name: str | None = None  # Optional session name
    demo_data_enabled: bool = True  # Whether to enable demo org_info data in sandbox
    user_work_area: str | None = None  # User's work area (e.g., "engineering")
    user_level: str | None = None  # User's level (e.g., "ic", "manager")
    # LLM selection from user's cookie
    llm_provider_type: str | None = None  # Provider type (e.g., "anthropic", "openai")
    llm_model_name: str | None = None  # Model name (e.g., "claude-opus-4-5")


class SessionUpdateRequest(BaseModel):
    """Request to update a build session.

    If name is None, the session name will be auto-generated using LLM.
    """

    name: str | None = None


class SessionNameGenerateResponse(BaseModel):
    """Response containing a generated session name."""

    name: str


class SandboxResponse(BaseModel):
    """Sandbox metadata in session response."""

    id: str
    status: SandboxStatus
    container_id: str | None
    created_at: datetime
    last_heartbeat: datetime | None

    @classmethod
    def from_model(cls, sandbox: Any) -> "SandboxResponse":
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
    def from_model(cls, artifact: Any) -> "ArtifactResponse":
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
    nextjs_port: int | None
    sandbox: SandboxResponse | None
    artifacts: list[ArtifactResponse]

    @classmethod
    def from_model(
        cls, session: "BuildSession", sandbox: Union["Sandbox", None] = None
    ) -> "SessionResponse":
        """Convert BuildSession ORM model to response.

        Args:
            session: BuildSession ORM model
            sandbox: Optional Sandbox ORM model. Since sandboxes are now user-owned
                     (not session-owned), the sandbox must be passed separately.
        """
        return cls(
            id=str(session.id),
            user_id=str(session.user_id) if session.user_id else None,
            name=session.name,
            status=session.status,
            created_at=session.created_at,
            last_activity_at=session.last_activity_at,
            nextjs_port=session.nextjs_port,
            sandbox=(SandboxResponse.from_model(sandbox) if sandbox else None),
            artifacts=[ArtifactResponse.from_model(a) for a in session.artifacts],
        )


class DetailedSessionResponse(SessionResponse):
    """Extended session response with sandbox state details.

    Used for single-session endpoints where we compute expensive fields
    like session_loaded_in_sandbox.
    """

    session_loaded_in_sandbox: bool

    @classmethod
    def from_session_response(
        cls,
        base: SessionResponse,
        session_loaded_in_sandbox: bool,
    ) -> "DetailedSessionResponse":
        return cls(
            **base.model_dump(),
            session_loaded_in_sandbox=session_loaded_in_sandbox,
        )


class SessionListResponse(BaseModel):
    """Response containing list of sessions."""

    sessions: list[SessionResponse]


# ===== Message Models =====
class MessageRequest(BaseModel):
    """Request to send a message to the CLI agent."""

    content: str


class MessageResponse(BaseModel):
    """Response containing message details.

    All message data is stored in message_metadata as JSON (the raw ACP packet).
    The turn_index groups all assistant responses under the user prompt they respond to.

    Packet types in message_metadata:
    - user_message: {type: "user_message", content: {...}}
    - agent_message: {type: "agent_message", content: {...}}
    - agent_thought: {type: "agent_thought", content: {...}}
    - tool_call_progress: {type: "tool_call_progress", status: "completed", ...}
    - agent_plan_update: {type: "agent_plan_update", entries: [...]}
    """

    id: str
    session_id: str
    turn_index: int
    type: MessageType
    message_metadata: dict[str, Any]
    created_at: datetime

    @classmethod
    def from_model(cls, message: Any) -> "MessageResponse":
        """Convert BuildMessage ORM model to response."""
        return cls(
            id=str(message.id),
            session_id=str(message.session_id),
            turn_index=message.turn_index,
            type=message.type,
            message_metadata=message.message_metadata,
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


class DirectoryListing(BaseModel):
    path: str  # Current directory path
    entries: list[FileSystemEntry]  # Contents


class WebappInfo(BaseModel):
    has_webapp: bool  # Whether a webapp exists in outputs/web
    webapp_url: str | None  # URL to access the webapp (e.g., http://localhost:3015)
    status: str  # Sandbox status (running, terminated, etc.)
    ready: bool  # Whether the NextJS dev server is actually responding


# ===== File Upload Models =====
class UploadResponse(BaseModel):
    """Response after successful file upload."""

    filename: str  # Sanitized filename
    path: str  # Relative path in sandbox (e.g., "attachments/doc.pdf")
    size_bytes: int  # File size in bytes


# ===== Rate Limit Models =====
class RateLimitResponse(BaseModel):
    """Rate limit information."""

    is_limited: bool
    limit_type: str  # "weekly" or "total"
    messages_used: int
    limit: int
    reset_timestamp: str | None = None


# ===== Pre-Provisioned Session Check Models =====
class PreProvisionedCheckResponse(BaseModel):
    """Response for checking if a pre-provisioned session is still valid (empty)."""

    valid: bool  # True if session exists and has no messages
    session_id: str | None = None  # Session ID if valid, None otherwise


# ===== Build Connector Models =====
class BuildConnectorStatus(str, Enum):
    """Status of a build connector."""

    NOT_CONNECTED = "not_connected"
    CONNECTED = "connected"
    CONNECTED_WITH_ERRORS = "connected_with_errors"
    INDEXING = "indexing"
    ERROR = "error"
    DELETING = "deleting"


class BuildConnectorInfo(BaseModel):
    """Simplified connector info for build admin panel."""

    cc_pair_id: int
    connector_id: int
    credential_id: int
    source: str
    name: str
    status: BuildConnectorStatus
    docs_indexed: int
    last_indexed: datetime | None
    error_message: str | None = None


class BuildConnectorListResponse(BaseModel):
    """List of build connectors."""

    connectors: list[BuildConnectorInfo]


# ===== Suggestion Bubble Models =====
class SuggestionTheme(str, Enum):
    """Theme/category of a follow-up suggestion."""

    ADD = "add"
    QUESTION = "question"


class SuggestionBubble(BaseModel):
    """A single follow-up suggestion bubble."""

    theme: SuggestionTheme
    text: str


class GenerateSuggestionsRequest(BaseModel):
    """Request to generate follow-up suggestions."""

    user_message: str  # First user message
    assistant_message: str  # First assistant text response (accumulated)


class GenerateSuggestionsResponse(BaseModel):
    """Response containing generated suggestions."""

    suggestions: list[SuggestionBubble]
