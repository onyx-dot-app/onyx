import json
import mimetypes
import os
from collections.abc import Generator
from pathlib import Path
from uuid import UUID
from uuid import uuid4

from acp.schema import AgentMessageChunk
from acp.schema import AgentPlanUpdate
from acp.schema import AgentThoughtChunk
from acp.schema import CurrentModeUpdate
from acp.schema import Error as ACPError
from acp.schema import PromptResponse
from acp.schema import ToolCallProgress
from acp.schema import ToolCallStart
from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import SandboxStatus
from onyx.db.models import User
from onyx.server.features.build.configs import PERSISTENT_DOCUMENT_STORAGE_PATH
from onyx.server.features.build.configs import SANDBOX_BASE_PATH
from onyx.server.features.build.db.sandbox import get_sandbox_by_session_id
from onyx.server.features.build.models import ArtifactInfo
from onyx.server.features.build.models import CreateSessionRequest
from onyx.server.features.build.models import CreateSessionResponse
from onyx.server.features.build.models import DirectoryListing
from onyx.server.features.build.models import ExecuteRequest
from onyx.server.features.build.models import FileSystemEntry
from onyx.server.features.build.models import SessionStatus
from onyx.server.features.build.sandbox.internal.agent_client import ACPEvent
from onyx.server.features.build.sandbox.manager import SandboxManager
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

session_router = APIRouter(prefix="/build")


# =============================================================================
# SSE Event Formatting Helpers
# =============================================================================


def _get_acp_event_type(event: ACPEvent) -> str:
    """Get the SSE event type from an ACP event.

    Maps ACP schema types to their sessionUpdate field value.
    """
    if isinstance(event, AgentMessageChunk):
        return "agent_message_chunk"
    elif isinstance(event, AgentThoughtChunk):
        return "agent_thought_chunk"
    elif isinstance(event, ToolCallStart):
        return "tool_call"
    elif isinstance(event, ToolCallProgress):
        return "tool_call_update"
    elif isinstance(event, AgentPlanUpdate):
        return "plan"
    elif isinstance(event, CurrentModeUpdate):
        return "current_mode_update"
    elif isinstance(event, PromptResponse):
        return "prompt_response"
    elif isinstance(event, ACPError):
        return "error"
    else:
        return "unknown"


def _format_sse_event(event_type: str, data: str) -> str:
    """Format an event as SSE.

    Args:
        event_type: The SSE event type name
        data: JSON string data (already serialized)

    Returns:
        Formatted SSE event string
    """
    return f"event: {event_type}\ndata: {data}\n\n"


def _format_status_event(status: str, message: str) -> str:
    """Format a status event as SSE."""
    data = json.dumps({"status": status, "message": message})
    return f"event: status\ndata: {data}\n\n"


def _status_to_string(status: SandboxStatus) -> str:
    """Convert SandboxStatus enum to string for API response."""
    if status == SandboxStatus.PROVISIONING:
        return "idle"
    elif status == SandboxStatus.RUNNING:
        return "running"
    elif status == SandboxStatus.IDLE:
        return "idle"
    elif status == SandboxStatus.TERMINATED:
        return "completed"
    elif status == SandboxStatus.FAILED:
        return "failed"
    else:
        return "idle"


# =============================================================================
# Session Management Endpoints
# =============================================================================


@session_router.post("/sessions")
def create_session(
    request: CreateSessionRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> CreateSessionResponse:
    """
    Create a new build session.

    Creates a sandbox with the necessary file structure and returns a session ID.
    Uses SandboxManager for database-backed sandbox provisioning.
    """
    session_id = str(uuid4())
    tenant_id = get_current_tenant_id()
    sandbox_manager = SandboxManager()

    try:
        sandbox_manager.provision(
            session_id=session_id,
            tenant_id=tenant_id,
            file_system_path=PERSISTENT_DOCUMENT_STORAGE_PATH or "/tmp/onyx-files",
            db_session=db_session,
        )
    except ValueError as e:
        # Max concurrent sandboxes reached
        raise HTTPException(status_code=429, detail=str(e))
    except RuntimeError as e:
        logger.error(f"Failed to provision sandbox: {e}")
        raise HTTPException(status_code=500, detail="Failed to create session")

    return CreateSessionResponse(session_id=session_id)


@session_router.get("/sessions/{session_id}")
def get_session_status(
    session_id: str,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> SessionStatus:
    """Get the status of a build session."""
    try:
        session_uuid = UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID format")

    sandbox = get_sandbox_by_session_id(db_session, session_uuid)
    if sandbox is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Determine webapp URL based on status
    webapp_url = None
    if sandbox.status.is_active():
        webapp_url = "/api/build/webapp"

    return SessionStatus(
        session_id=session_id,
        status=_status_to_string(sandbox.status),
        webapp_url=webapp_url,
    )


@session_router.delete("/sessions/{session_id}")
def delete_session(
    session_id: str,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    """
    Delete a build session and cleanup its sandbox.
    """
    try:
        session_uuid = UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID format")

    sandbox = get_sandbox_by_session_id(db_session, session_uuid)
    if sandbox is None:
        raise HTTPException(status_code=404, detail="Session not found")

    sandbox_manager = SandboxManager()
    sandbox_manager.terminate(str(sandbox.id), db_session)


@session_router.post("/sessions/{session_id}/execute")
def execute_task(
    session_id: str,
    request: ExecuteRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> StreamingResponse:
    """
    Execute a task in the build session.

    Returns an SSE stream with ACP events directly from the agent:
    - agent_message_chunk: Text/image content from agent
    - agent_thought_chunk: Agent's internal reasoning
    - tool_call: Tool invocation started
    - tool_call_update: Tool execution progress/result
    - plan: Agent's execution plan
    - current_mode_update: Agent mode change
    - prompt_response: Agent finished (contains stop_reason)
    - error: An error occurred
    - status: Internal status updates
    """
    try:
        session_uuid = UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID format")

    sandbox = get_sandbox_by_session_id(db_session, session_uuid)
    if sandbox is None:
        raise HTTPException(status_code=404, detail="Session not found")

    sandbox_manager = SandboxManager()

    def event_generator() -> Generator[str, None, None]:
        try:
            yield _format_status_event("running", "Starting agent...")

            # Stream ACP events directly from SandboxManager.send_message()
            for acp_event in sandbox_manager.send_message(
                str(sandbox.id), request.task, db_session
            ):
                event_type = _get_acp_event_type(acp_event)
                # Use pydantic model's JSON serialization
                event_data = acp_event.model_dump_json()
                yield _format_sse_event(event_type, event_data)

                # Check for completion/error in prompt_response
                if isinstance(acp_event, PromptResponse):
                    stop_reason = getattr(acp_event, "stop_reason", None)
                    if stop_reason:
                        yield _format_status_event(
                            "completed", f"Agent stopped: {stop_reason}"
                        )
                    else:
                        yield _format_status_event("completed", "Task completed")

                elif isinstance(acp_event, ACPError):
                    yield _format_status_event("failed", acp_event.message)

            # Check for webapp artifact
            sandbox_path = Path(SANDBOX_BASE_PATH) / str(sandbox.session_id)
            web_dir = sandbox_path / "outputs" / "web"
            if web_dir.exists():
                artifact_data = json.dumps(
                    {
                        "artifact_type": "webapp",
                        "path": str(web_dir),
                        "filename": "webapp",
                    }
                )
                yield _format_sse_event("artifact", artifact_data)

        except ValueError as e:
            logger.error(f"Error executing task: {e}")
            yield _format_sse_event("error", json.dumps({"message": str(e)}))
            yield _format_status_event("failed", str(e))
        except RuntimeError as e:
            logger.error(f"Agent communication error: {e}")
            yield _format_sse_event("error", json.dumps({"message": str(e)}))
            yield _format_status_event("failed", str(e))
        except Exception as e:
            logger.error(f"Unexpected error executing task: {e}")
            yield _format_sse_event("error", json.dumps({"message": str(e)}))
            yield _format_status_event("failed", str(e))

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


# =============================================================================
# Artifact Endpoints
# =============================================================================


@session_router.get("/sessions/{session_id}/artifacts")
def list_artifacts(
    session_id: str,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[ArtifactInfo]:
    """List artifacts generated in the session."""
    try:
        session_uuid = UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID format")

    sandbox = get_sandbox_by_session_id(db_session, session_uuid)
    if sandbox is None:
        raise HTTPException(status_code=404, detail="Session not found")

    sandbox_path = Path(SANDBOX_BASE_PATH) / str(sandbox.session_id)
    artifacts: list[ArtifactInfo] = []
    output_dir = sandbox_path / "outputs"

    if not output_dir.exists():
        return artifacts

    # Check for webapp
    web_dir = output_dir / "web"
    if web_dir.exists():
        artifacts.append(
            ArtifactInfo(
                artifact_type="webapp",
                path="outputs/web",
                filename="webapp",
                mime_type="application/x-directory",
            )
        )

    # Scan for other generated files
    for root, _, files in os.walk(output_dir):
        for filename in files:
            # Skip common non-artifact files
            if filename.startswith(".") or filename in (
                "package.json",
                "package-lock.json",
                "tsconfig.json",
            ):
                continue

            file_path = Path(root) / filename
            rel_path = file_path.relative_to(sandbox_path)
            mime_type, _ = mimetypes.guess_type(str(file_path))

            # Determine artifact type
            if mime_type and mime_type.startswith("image/"):
                artifact_type = "image"
            elif filename.endswith(".md"):
                artifact_type = "markdown"
            else:
                artifact_type = "file"

            artifacts.append(
                ArtifactInfo(
                    artifact_type=artifact_type,
                    path=str(rel_path),
                    filename=filename,
                    mime_type=mime_type,
                )
            )

    return artifacts


# Hidden directories/files to filter from listings
HIDDEN_PATTERNS = {
    ".venv",
    ".git",
    ".next",
    "__pycache__",
    "node_modules",
    ".DS_Store",
    ".env",
    ".gitignore",
}


@session_router.get("/sessions/{session_id}/files")
def list_directory(
    session_id: str,
    path: str = "",
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> DirectoryListing:
    """
    List files and directories in the sandbox.

    Args:
        session_id: The session ID
        path: Relative path from sandbox root (empty string for root)

    Returns:
        DirectoryListing with sorted entries (directories first, then files)
    """
    try:
        session_uuid = UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID format")

    sandbox = get_sandbox_by_session_id(db_session, session_uuid)
    if sandbox is None:
        raise HTTPException(status_code=404, detail="Session not found")

    sandbox_path = Path(SANDBOX_BASE_PATH) / str(sandbox.session_id)

    # Construct the target directory path
    target_dir = sandbox_path / path if path else sandbox_path

    # Security check: ensure path doesn't escape sandbox via .. traversal
    # We check the path components before resolving symlinks
    try:
        # Normalize without resolving symlinks to check for .. escapes
        normalized = os.path.normpath(str(target_dir))
        sandbox_normalized = os.path.normpath(str(sandbox_path))
        if not normalized.startswith(sandbox_normalized):
            raise HTTPException(status_code=403, detail="Access denied")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target_dir.exists():
        raise HTTPException(status_code=404, detail="Directory not found")

    if not target_dir.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")

    entries: list[FileSystemEntry] = []

    for item in target_dir.iterdir():
        # Filter hidden files and directories
        if item.name in HIDDEN_PATTERNS or item.name.startswith("."):
            continue

        # Compute relative path from the logical path, not the resolved path
        # This handles symlinked directories correctly
        rel_path = f"{path}/{item.name}" if path else item.name
        is_dir = item.is_dir()

        entry = FileSystemEntry(
            name=item.name,
            path=rel_path,
            is_directory=is_dir,
            size=item.stat().st_size if not is_dir else None,
            mime_type=mimetypes.guess_type(str(item))[0] if not is_dir else None,
        )
        entries.append(entry)

    # Sort: directories first, then files, both alphabetically
    entries.sort(key=lambda e: (not e.is_directory, e.name.lower()))

    return DirectoryListing(path=path, entries=entries)


@session_router.get("/sessions/{session_id}/artifacts/{path:path}")
def download_artifact(
    session_id: str,
    path: str,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> Response:
    """Download a specific artifact file."""
    try:
        session_uuid = UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID format")

    sandbox = get_sandbox_by_session_id(db_session, session_uuid)
    if sandbox is None:
        raise HTTPException(status_code=404, detail="Session not found")

    sandbox_path = Path(SANDBOX_BASE_PATH) / str(sandbox.session_id)
    file_path = sandbox_path / path

    # Security check: ensure path doesn't escape sandbox
    try:
        file_path = file_path.resolve()
        sandbox_path_resolved = sandbox_path.resolve()
        if not str(file_path).startswith(str(sandbox_path_resolved)):
            raise HTTPException(status_code=403, detail="Access denied")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")

    if file_path.is_dir():
        raise HTTPException(status_code=400, detail="Cannot download directory")

    content = file_path.read_bytes()
    mime_type, _ = mimetypes.guess_type(str(file_path))

    return Response(
        content=content,
        media_type=mime_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{file_path.name}"',
        },
    )
