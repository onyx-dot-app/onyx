"""
CC4A Build API v1 - Returns dummy data for frontend development.

Based on the specification in cc4a-overview.md.
"""

import json
import uuid
from collections.abc import Generator
from datetime import datetime
from enum import Enum
from typing import Literal

from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import HTTPException
from fastapi import Query
from fastapi import UploadFile
from fastapi.responses import Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.configs.constants import DocumentSource
from onyx.db.connector_credential_pair import get_connector_credential_pairs_for_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import IndexingStatus
from onyx.db.enums import ProcessingMode
from onyx.db.index_attempt import get_latest_index_attempt_for_cc_pair_id
from onyx.db.models import User


# =============================================================================
# Build Connector Models
# =============================================================================


class BuildConnectorStatus(str, Enum):
    """Status of a build connector."""

    NOT_CONNECTED = "not_connected"
    CONNECTED = "connected"
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


# =============================================================================
# In-Memory Session Store (for dummy data persistence)
# =============================================================================

# Stores sessions by ID
_sessions_store: dict[str, "SessionResponse"] = {}

# Stores messages by session_id
_messages_store: dict[str, list["MessageResponse"]] = {}

# Stores artifacts by session_id
_artifacts_store: dict[str, list["ArtifactMetadataResponse"]] = {}


# =============================================================================
# Streaming Protocol Models
# =============================================================================


class StreamingType(str, Enum):
    """Enum defining all streaming packet types."""

    DONE = "done"
    ERROR = "error"
    STEP_START = "step_start"
    STEP_DELTA = "step_delta"
    STEP_END = "step_end"
    OUTPUT_START = "output_start"
    OUTPUT_DELTA = "output_delta"
    ARTIFACT_CREATED = "artifact_created"
    ARTIFACT_UPDATED = "artifact_updated"
    TOOL_START = "tool_start"
    TOOL_OUTPUT = "tool_output"
    TOOL_END = "tool_end"
    FILE_WRITE = "file_write"
    FILE_DELETE = "file_delete"


class ArtifactType(str, Enum):
    NEXTJS_APP = "nextjs_app"
    PPTX = "pptx"
    MARKDOWN = "markdown"
    CHART = "chart"
    CSV = "csv"
    IMAGE = "image"


class SessionStatusEnum(str, Enum):
    ACTIVE = "active"
    IDLE = "idle"
    ARCHIVED = "archived"


# =============================================================================
# Request/Response Models
# =============================================================================


class CreateSessionRequest(BaseModel):
    """Request to create a new build session."""

    name: str | None = None
    description: str | None = None


class SessionResponse(BaseModel):
    """Session details response."""

    id: str
    org_id: str
    user_id: str
    sandbox_id: str | None = None
    name: str | None = None
    status: SessionStatusEnum
    created_at: datetime
    last_activity_at: datetime


class SessionListResponse(BaseModel):
    """List of sessions response."""

    sessions: list[SessionResponse]
    total: int


class SendMessageRequest(BaseModel):
    """Request to send a message to the agent."""

    content: str
    context: str | None = None


class MessageResponse(BaseModel):
    """A single message in the conversation."""

    id: str
    session_id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class MessageHistoryResponse(BaseModel):
    """Message history response."""

    messages: list[MessageResponse]


class ArtifactMetadataResponse(BaseModel):
    """Artifact metadata."""

    id: str
    session_id: str
    type: ArtifactType
    path: str
    name: str
    created_at: datetime
    updated_at: datetime
    preview_url: str | None = None


class ArtifactListResponse(BaseModel):
    """List of artifacts response."""

    artifacts: list[ArtifactMetadataResponse]


class FileSystemEntry(BaseModel):
    """A file or directory entry."""

    name: str
    path: str
    is_directory: bool
    size: int | None = None
    mime_type: str | None = None
    modified_at: datetime | None = None


class DirectoryListingResponse(BaseModel):
    """Directory listing response."""

    path: str
    entries: list[FileSystemEntry]


class RenameSessionRequest(BaseModel):
    """Request to rename a session."""

    name: str | None = None  # If None, triggers auto-naming


class RateLimitResponse(BaseModel):
    """Rate limit information."""

    is_limited: bool
    limit_type: Literal["weekly", "total"]
    messages_used: int
    limit: int
    reset_timestamp: str | None = None


class UploadResponse(BaseModel):
    """File upload response."""

    path: str
    size: int
    name: str


# =============================================================================
# Dummy Data Generators
# =============================================================================


def _generate_dummy_directory_listing(path: str) -> list[FileSystemEntry]:
    """Generate dummy directory listing."""
    if path == "" or path == "/outputs":
        return [
            FileSystemEntry(
                name="web",
                path="web/",
                is_directory=True,
                modified_at=datetime.utcnow(),
            ),
            FileSystemEntry(
                name="documents",
                path="documents/",
                is_directory=True,
                modified_at=datetime.utcnow(),
            ),
            FileSystemEntry(
                name="presentations",
                path="presentations/",
                is_directory=True,
                modified_at=datetime.utcnow(),
            ),
            FileSystemEntry(
                name="manifest.json",
                path="manifest.json",
                is_directory=False,
                size=256,
                mime_type="application/json",
                modified_at=datetime.utcnow(),
            ),
        ]
    elif "web" in path:
        return [
            FileSystemEntry(
                name="src",
                path=f"{path}/src",
                is_directory=True,
                modified_at=datetime.utcnow(),
            ),
            FileSystemEntry(
                name="package.json",
                path=f"{path}/package.json",
                is_directory=False,
                size=1024,
                mime_type="application/json",
                modified_at=datetime.utcnow(),
            ),
        ]
    return []


def _format_sse_event(event_type: str, data: dict) -> str:
    """Format an event as SSE."""
    return f"event: message\ndata: {json.dumps(data)}\n\n"


def _generate_streaming_response(session_id: str) -> Generator[str, None, None]:
    """Generate a dummy streaming response simulating agent activity."""
    import time

    step_id = str(uuid.uuid4())

    # Step 1: Start
    yield _format_sse_event(
        "message",
        {
            "type": "step_start",
            "step_id": step_id,
            "title": "Analyzing requirements",
            "timestamp": datetime.utcnow().isoformat(),
        },
    )
    time.sleep(0.3)

    # Step 1: Delta
    yield _format_sse_event(
        "message",
        {
            "type": "step_delta",
            "step_id": step_id,
            "content": "Reading your requirements and planning the implementation...",
            "timestamp": datetime.utcnow().isoformat(),
        },
    )
    time.sleep(0.3)

    # Step 1: End
    yield _format_sse_event(
        "message",
        {
            "type": "step_end",
            "step_id": step_id,
            "status": "success",
            "timestamp": datetime.utcnow().isoformat(),
        },
    )

    # Tool usage
    yield _format_sse_event(
        "message",
        {
            "type": "tool_start",
            "tool_name": "write_file",
            "tool_input": {"path": "/outputs/web/src/App.tsx"},
            "timestamp": datetime.utcnow().isoformat(),
        },
    )
    time.sleep(0.2)

    yield _format_sse_event(
        "message",
        {
            "type": "file_write",
            "path": "web/src/App.tsx",
            "size_bytes": 1523,
            "timestamp": datetime.utcnow().isoformat(),
        },
    )

    yield _format_sse_event(
        "message",
        {
            "type": "tool_end",
            "tool_name": "write_file",
            "status": "success",
            "timestamp": datetime.utcnow().isoformat(),
        },
    )

    # Artifact created - store it
    artifact_id = str(uuid.uuid4())
    artifact = ArtifactMetadataResponse(
        id=artifact_id,
        session_id=session_id,
        type=ArtifactType.NEXTJS_APP,
        path="web/",
        name="Dashboard",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        preview_url=f"/api/build/v1/sessions/{session_id}/preview",
    )
    if session_id in _artifacts_store:
        _artifacts_store[session_id].append(artifact)

    yield _format_sse_event(
        "message",
        {
            "type": "artifact_created",
            "artifact": {
                "id": artifact_id,
                "type": "nextjs_app",
                "name": "Dashboard",
                "path": "web/",
                "preview_url": f"/api/build/v1/sessions/{session_id}/preview",
            },
            "timestamp": datetime.utcnow().isoformat(),
        },
    )

    # Output start
    yield _format_sse_event(
        "message",
        {
            "type": "output_start",
            "timestamp": datetime.utcnow().isoformat(),
        },
    )

    # Output delta (streaming the response)
    response_parts = [
        "I've built your dashboard ",
        "with the following features:\n\n",
        "- Interactive charts using Recharts\n",
        "- Responsive layout\n",
        "- Dark mode support\n\n",
        "You can preview it in the artifact panel.",
    ]
    full_response = ""
    for part in response_parts:
        full_response += part
        yield _format_sse_event(
            "message",
            {
                "type": "output_delta",
                "content": part,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
        time.sleep(0.1)

    # Store assistant message
    assistant_message = MessageResponse(
        id=str(uuid.uuid4()),
        session_id=session_id,
        role="assistant",
        content=full_response,
        created_at=datetime.utcnow(),
    )
    if session_id in _messages_store:
        _messages_store[session_id].append(assistant_message)

    # Done
    yield _format_sse_event(
        "message",
        {
            "type": "done",
            "summary": "Created a Next.js dashboard with charts",
            "timestamp": datetime.utcnow().isoformat(),
        },
    )


# =============================================================================
# API Router
# =============================================================================

v1_router = APIRouter(prefix="/build/v1")


# -----------------------------------------------------------------------------
# Sessions
# -----------------------------------------------------------------------------


@v1_router.post("/sessions", response_model=SessionResponse)
def create_session(
    request: CreateSessionRequest,
    user: User | None = Depends(current_user),
) -> SessionResponse:
    """Create a new build session."""
    session_id = str(uuid.uuid4())
    user_id = str(user.id) if user else str(uuid.uuid4())
    org_id = str(uuid.uuid4())  # Would come from user context in real impl

    session = SessionResponse(
        id=session_id,
        org_id=org_id,
        user_id=user_id,
        sandbox_id=str(uuid.uuid4()),
        status=SessionStatusEnum.ACTIVE,
        created_at=datetime.utcnow(),
        last_activity_at=datetime.utcnow(),
    )

    _sessions_store[session_id] = session
    _messages_store[session_id] = []
    _artifacts_store[session_id] = []

    return session


@v1_router.put("/sessions/{session_id}", response_model=SessionResponse)
def get_and_wake_session(
    session_id: str,
    user: User | None = Depends(current_user),
) -> SessionResponse:
    """Get session details and wake it up if idle."""
    if session_id not in _sessions_store:
        raise HTTPException(status_code=404, detail="Session not found")

    session = _sessions_store[session_id]
    # Wake up if idle
    if session.status == SessionStatusEnum.IDLE:
        session.status = SessionStatusEnum.ACTIVE
    session.last_activity_at = datetime.utcnow()
    return session


@v1_router.get("/sessions", response_model=SessionListResponse)
def list_sessions(
    status: SessionStatusEnum | None = Query(None),
    user: User | None = Depends(current_user),
) -> SessionListResponse:
    """List all sessions with optional filters."""
    sessions = list(_sessions_store.values())

    # Filter by status if provided
    if status is not None:
        sessions = [s for s in sessions if s.status == status]

    # Filter by user if authenticated
    if user is not None:
        user_id = str(user.id)
        sessions = [s for s in sessions if s.user_id == user_id]

    # Sort by last_activity_at descending
    sessions.sort(key=lambda s: s.last_activity_at, reverse=True)

    return SessionListResponse(sessions=sessions, total=len(sessions))


@v1_router.delete("/sessions/{session_id}")
def delete_session(
    session_id: str,
    user: User | None = Depends(current_user),
) -> dict:
    """End session and perform full cleanup."""
    if session_id not in _sessions_store:
        raise HTTPException(status_code=404, detail="Session not found")

    del _sessions_store[session_id]
    _messages_store.pop(session_id, None)
    _artifacts_store.pop(session_id, None)

    return {"status": "deleted", "session_id": session_id}


@v1_router.put("/sessions/{session_id}/name", response_model=SessionResponse)
def rename_session(
    session_id: str,
    request: RenameSessionRequest,
    user: User | None = Depends(current_user),
) -> SessionResponse:
    """Rename a session. If name is None, auto-generate from first message."""
    if session_id not in _sessions_store:
        raise HTTPException(status_code=404, detail="Session not found")

    session = _sessions_store[session_id]

    if request.name is not None:
        # Manual rename
        session.name = request.name
    else:
        # Auto-generate name from first user message (simulating LLM naming)
        messages = _messages_store.get(session_id, [])
        first_user_msg = next((m for m in messages if m.role == "user"), None)
        if first_user_msg:
            content = first_user_msg.content
            session.name = content[:40].strip() + ("..." if len(content) > 40 else "")
        else:
            session.name = f"Build Session {session_id[:8]}"

    session.last_activity_at = datetime.utcnow()
    return session


# -----------------------------------------------------------------------------
# Messages
# -----------------------------------------------------------------------------


@v1_router.post("/sessions/{session_id}/messages")
def send_message(
    session_id: str,
    request: SendMessageRequest,
    user: User | None = Depends(current_user),
) -> StreamingResponse:
    """Send a message to the agent and receive streaming response."""
    if session_id not in _sessions_store:
        raise HTTPException(status_code=404, detail="Session not found")

    # Store the user message
    user_message = MessageResponse(
        id=str(uuid.uuid4()),
        session_id=session_id,
        role="user",
        content=request.content,
        created_at=datetime.utcnow(),
    )
    _messages_store[session_id].append(user_message)

    # Update session activity
    _sessions_store[session_id].last_activity_at = datetime.utcnow()

    return StreamingResponse(
        _generate_streaming_response(session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@v1_router.get("/sessions/{session_id}/messages", response_model=MessageHistoryResponse)
def get_message_history(
    session_id: str,
    user: User | None = Depends(current_user),
) -> MessageHistoryResponse:
    """Get message history for a session."""
    if session_id not in _sessions_store:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = _messages_store.get(session_id, [])
    return MessageHistoryResponse(messages=messages)


# -----------------------------------------------------------------------------
# Artifacts
# -----------------------------------------------------------------------------


@v1_router.get("/sessions/{session_id}/artifacts", response_model=ArtifactListResponse)
def list_artifacts(
    session_id: str,
    user: User | None = Depends(current_user),
) -> ArtifactListResponse:
    """List all artifacts in the session."""
    if session_id not in _sessions_store:
        raise HTTPException(status_code=404, detail="Session not found")

    artifacts = _artifacts_store.get(session_id, [])
    return ArtifactListResponse(artifacts=artifacts)


@v1_router.get(
    "/sessions/{session_id}/artifacts/{artifact_id}",
    response_model=ArtifactMetadataResponse,
)
def get_artifact_metadata(
    session_id: str,
    artifact_id: str,
    user: User | None = Depends(current_user),
) -> ArtifactMetadataResponse:
    """Get metadata for a specific artifact."""
    if session_id not in _sessions_store:
        raise HTTPException(status_code=404, detail="Session not found")

    artifacts = _artifacts_store.get(session_id, [])
    for artifact in artifacts:
        if artifact.id == artifact_id:
            return artifact

    raise HTTPException(status_code=404, detail="Artifact not found")


@v1_router.get("/sessions/{session_id}/artifacts/{artifact_id}/content")
def get_artifact_content(
    session_id: str,
    artifact_id: str,
    user: User | None = Depends(current_user),
) -> Response:
    """Download/stream artifact content."""
    if session_id not in _sessions_store:
        raise HTTPException(status_code=404, detail="Session not found")

    # Return dummy content
    dummy_content = b"// Dummy artifact content\nexport default function App() {\n  return <div>Hello World</div>;\n}\n"
    return Response(
        content=dummy_content,
        media_type="text/plain",
        headers={"Content-Disposition": 'attachment; filename="App.tsx"'},
    )


# -----------------------------------------------------------------------------
# Filesystem (VM Explorer)
# -----------------------------------------------------------------------------


@v1_router.post("/sessions/{session_id}/fs/upload", response_model=UploadResponse)
async def upload_file(
    session_id: str,
    file: UploadFile = File(...),
    user: User | None = Depends(current_user),
) -> UploadResponse:
    """Upload a file to the sandbox."""
    if session_id not in _sessions_store:
        raise HTTPException(status_code=404, detail="Session not found")

    content = await file.read()
    return UploadResponse(
        path=f"/user-input/{file.filename}",
        size=len(content),
        name=file.filename or "unknown",
    )


@v1_router.get("/sessions/{session_id}/fs", response_model=DirectoryListingResponse)
def list_directory(
    session_id: str,
    path: str = Query("/outputs", description="Path to list"),
    user: User | None = Depends(current_user),
) -> DirectoryListingResponse:
    """List directory contents in the sandbox."""
    if session_id not in _sessions_store:
        raise HTTPException(status_code=404, detail="Session not found")

    return DirectoryListingResponse(
        path=path,
        entries=_generate_dummy_directory_listing(path),
    )


@v1_router.get("/sessions/{session_id}/fs/read")
def read_file(
    session_id: str,
    path: str = Query(..., description="Path to read"),
    user: User | None = Depends(current_user),
) -> Response:
    """Read file content from the sandbox."""
    if session_id not in _sessions_store:
        raise HTTPException(status_code=404, detail="Session not found")

    # Return dummy content based on file extension
    if path.endswith(".json"):
        content = b'{\n  "name": "dashboard",\n  "version": "1.0.0"\n}'
        media_type = "application/json"
    elif path.endswith(".md"):
        content = b"# Dashboard\n\nThis is a generated dashboard application."
        media_type = "text/markdown"
    elif path.endswith(".tsx") or path.endswith(".ts"):
        content = (
            b"export default function Component() {\n  return <div>Hello</div>;\n}"
        )
        media_type = "text/typescript"
    else:
        content = b"Dummy file content"
        media_type = "text/plain"

    return Response(content=content, media_type=media_type)


# -----------------------------------------------------------------------------
# Rate Limiting
# -----------------------------------------------------------------------------


@v1_router.get("/limit", response_model=RateLimitResponse)
def get_rate_limit(
    user: User | None = Depends(current_user),
) -> RateLimitResponse:
    """Get rate limit information for the current user."""
    is_paid = user is not None  # Simplified logic

    # Count total user messages across all sessions
    total_messages = 0
    for session_id in _messages_store:
        messages = _messages_store[session_id]
        total_messages += sum(1 for m in messages if m.role == "user")

    limit = 50 if is_paid else 10
    is_limited = total_messages >= limit

    return RateLimitResponse(
        is_limited=is_limited,
        limit_type="weekly" if is_paid else "total",
        messages_used=total_messages,
        limit=limit,
        reset_timestamp=datetime.utcnow().isoformat() if is_paid else None,
    )


# -----------------------------------------------------------------------------
# Build Connectors
# -----------------------------------------------------------------------------


@v1_router.get("/connectors", response_model=BuildConnectorListResponse)
def get_build_connectors(
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> BuildConnectorListResponse:
    """Get all connectors for the build admin panel.

    Returns all connector-credential pairs with simplified status information.
    """
    cc_pairs = get_connector_credential_pairs_for_user(
        db_session=db_session,
        user=user,
        get_editable=False,
        eager_load_connector=True,
        eager_load_credential=True,
        processing_mode=ProcessingMode.FILE_SYSTEM,  # Only show FILE_SYSTEM connectors
    )

    connectors: list[BuildConnectorInfo] = []
    for cc_pair in cc_pairs:
        # Skip ingestion API connectors and default pairs
        if cc_pair.connector.source == DocumentSource.INGESTION_API:
            continue
        if cc_pair.name == "DefaultCCPair":
            continue

        # Determine status
        error_message: str | None = None

        if cc_pair.status == ConnectorCredentialPairStatus.DELETING:
            status = BuildConnectorStatus.DELETING
        elif cc_pair.status == ConnectorCredentialPairStatus.INVALID:
            status = BuildConnectorStatus.ERROR
            error_message = "Connector credentials are invalid"
        else:
            # Check latest index attempt for errors
            latest_attempt = get_latest_index_attempt_for_cc_pair_id(
                db_session=db_session,
                connector_credential_pair_id=cc_pair.id,
                secondary_index=False,
                only_finished=True,
            )

            if latest_attempt and latest_attempt.status == IndexingStatus.FAILED:
                status = BuildConnectorStatus.ERROR
                error_message = latest_attempt.error_msg
            elif (
                latest_attempt
                and latest_attempt.status == IndexingStatus.COMPLETED_WITH_ERRORS
            ):
                status = BuildConnectorStatus.ERROR
                error_message = "Indexing completed with errors"
            elif cc_pair.status == ConnectorCredentialPairStatus.PAUSED:
                status = BuildConnectorStatus.CONNECTED
            elif cc_pair.last_successful_index_time is None:
                # Never successfully indexed - check if currently indexing
                # First check cc_pair status for scheduled/initial indexing
                if cc_pair.status in (
                    ConnectorCredentialPairStatus.SCHEDULED,
                    ConnectorCredentialPairStatus.INITIAL_INDEXING,
                ):
                    status = BuildConnectorStatus.INDEXING
                else:
                    in_progress_attempt = get_latest_index_attempt_for_cc_pair_id(
                        db_session=db_session,
                        connector_credential_pair_id=cc_pair.id,
                        secondary_index=False,
                        only_finished=False,
                    )
                    if (
                        in_progress_attempt
                        and in_progress_attempt.status == IndexingStatus.IN_PROGRESS
                    ):
                        status = BuildConnectorStatus.INDEXING
                    elif (
                        in_progress_attempt
                        and in_progress_attempt.status == IndexingStatus.NOT_STARTED
                    ):
                        status = BuildConnectorStatus.INDEXING
                    else:
                        # Has a finished attempt but never succeeded - likely error
                        status = BuildConnectorStatus.ERROR
                        error_message = (
                            latest_attempt.error_msg
                            if latest_attempt
                            else "Initial indexing failed"
                        )
            else:
                status = BuildConnectorStatus.CONNECTED

        connectors.append(
            BuildConnectorInfo(
                cc_pair_id=cc_pair.id,
                connector_id=cc_pair.connector.id,
                credential_id=cc_pair.credential.id,
                source=cc_pair.connector.source.value,
                name=cc_pair.name or cc_pair.connector.name or "Unnamed",
                status=status,
                docs_indexed=0,  # Would need to query for this
                last_indexed=cc_pair.last_successful_index_time,
                error_message=error_message,
            )
        )

    return BuildConnectorListResponse(connectors=connectors)
