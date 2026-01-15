import json
import mimetypes
import os
import queue
import threading
from collections.abc import Generator
from dataclasses import asdict
from pathlib import Path

from claude_agent_sdk import AssistantMessage
from claude_agent_sdk import Message
from claude_agent_sdk import ResultMessage
from claude_agent_sdk.types import ContentBlock
from claude_agent_sdk.types import TextBlock
from claude_agent_sdk.types import ThinkingBlock
from claude_agent_sdk.types import ToolResultBlock
from claude_agent_sdk.types import ToolUseBlock
from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Response
from fastapi.responses import StreamingResponse

from onyx.auth.users import current_user
from onyx.db.models import User
from onyx.server.features.build.models import ArtifactInfo
from onyx.server.features.build.models import CreateSessionRequest
from onyx.server.features.build.models import CreateSessionResponse
from onyx.server.features.build.models import ExecuteRequest
from onyx.server.features.build.models import SessionStatus
from onyx.server.features.build.session_manager import get_session_manager
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

session_router = APIRouter(prefix="/build")


# =============================================================================
# SSE Event Formatting Helpers
# =============================================================================


def _content_block_to_sse_event(block: ContentBlock) -> dict:
    """Convert a content block to an SSE event payload."""
    if isinstance(block, TextBlock):
        return {
            "type": "output",
            "data": {"stream": "stdout", "data": block.text},
        }
    elif isinstance(block, ThinkingBlock):
        return {
            "type": "output",
            "data": {"stream": "stdout", "data": f"[Thinking] {block.thinking}"},
        }
    elif isinstance(block, ToolUseBlock):
        return {
            "type": "output",
            "data": {
                "stream": "stdout",
                "data": f"[Tool: {block.name}] {json.dumps(block.input)}",
            },
        }
    elif isinstance(block, ToolResultBlock):
        content = block.content
        if isinstance(content, str) and len(content) > 500:
            content = content[:500] + "... (truncated)"
        return {
            "type": "output",
            "data": {
                "stream": "stderr" if block.is_error else "stdout",
                "data": f"[Tool Result] {content}",
            },
        }
    else:
        return {
            "type": "output",
            "data": {"stream": "stdout", "data": str(asdict(block))},
        }


def _message_to_sse_events(message: Message) -> list[dict]:
    """Convert an SDK message to SSE event payloads."""
    events = []

    if isinstance(message, AssistantMessage):
        for block in message.content:
            events.append(_content_block_to_sse_event(block))

    elif isinstance(message, ResultMessage):
        status = "completed" if not message.is_error else "failed"
        status_message = message.result or ""
        if message.total_cost_usd is not None:
            status_message += f" (Cost: ${message.total_cost_usd:.4f})"
        events.append(
            {
                "type": "status",
                "data": {"status": status, "message": status_message},
            }
        )

    return events


def _format_sse_event(event_type: str, data: dict) -> str:
    """Format an event as SSE."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


# =============================================================================
# Session Management Endpoints
# =============================================================================


@session_router.post("/sessions")
def create_session(
    request: CreateSessionRequest,
    user: User | None = Depends(current_user),
) -> CreateSessionResponse:
    """
    Create a new build session.

    Creates a sandbox with the necessary file structure and returns a session ID.
    """
    manager = get_session_manager()

    user_id = str(user.id) if user else None
    tenant_id = get_current_tenant_id()

    session_id = manager.create_session(
        task=request.task,
        user_id=user_id,
        tenant_id=tenant_id,
    )

    return CreateSessionResponse(session_id=session_id)


@session_router.get("/sessions/{session_id}")
def get_session_status(
    session_id: str,
    user: User | None = Depends(current_user),
) -> SessionStatus:
    """Get the status of a build session."""
    manager = get_session_manager()
    session = manager.get_session(session_id)

    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    webapp_url = None
    if session.sandbox and session.status in ("running", "completed"):
        webapp_url = "/api/build/webapp"

    return SessionStatus(
        session_id=session_id,
        status=session.status,
        webapp_url=webapp_url,
    )


@session_router.delete("/sessions/{session_id}")
def delete_session(
    session_id: str,
    user: User | None = Depends(current_user),
) -> None:
    """
    Delete a build session and cleanup its sandbox.
    """
    manager = get_session_manager()
    deleted = manager.delete_session(session_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")


@session_router.post("/sessions/{session_id}/execute")
def execute_task(
    session_id: str,
    request: ExecuteRequest,
    user: User | None = Depends(current_user),
) -> StreamingResponse:
    """
    Execute a task in the build session.

    Returns an SSE stream with output, status, and artifact events.
    """
    manager = get_session_manager()
    session = manager.get_session(session_id)

    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Update session status
    manager.update_session(session_id, status="running")

    # Create a queue for message passing between threads
    message_queue: queue.Queue[Message | None] = queue.Queue()

    def message_emitter(message: Message) -> None:
        """Emitter callback that puts messages into the queue."""
        message_queue.put(message)

    def run_agent_thread() -> None:
        """Run the agent in a background thread."""
        try:
            client = manager.client
            sandbox = client.run_cli_agent(
                sandbox_id=session_id,
                task=request.task,
                emitter=message_emitter,
            )
            # Store sandbox in session
            manager.update_session(session_id, sandbox=sandbox)
        except Exception as e:
            logger.error(f"Agent thread error: {e}")
            # Put error as a special message
            message_queue.put(None)
            raise
        finally:
            # Signal completion
            message_queue.put(None)

    def event_generator() -> Generator[str, None, None]:
        try:
            yield _format_sse_event(
                "status", {"status": "running", "message": "Starting build..."}
            )

            # Start the agent in a background thread
            agent_thread = threading.Thread(target=run_agent_thread, daemon=True)
            agent_thread.start()

            yield _format_sse_event(
                "status", {"status": "running", "message": "Running agent..."}
            )

            # Stream messages from the queue
            while True:
                message = message_queue.get()
                if message is None:
                    break
                events = _message_to_sse_events(message)
                for event in events:
                    event_type = event.get("type", "output")
                    data = event.get("data", event)
                    yield _format_sse_event(event_type, data)

            # Wait for the thread to finish
            agent_thread.join(timeout=5.0)

            # Get the sandbox from session to check for webapp
            session = manager.get_session(session_id)
            if session and session.sandbox:
                web_dir = session.sandbox.path / "outputs" / "web"
                if web_dir.exists():
                    yield _format_sse_event(
                        "artifact",
                        {
                            "artifact_type": "webapp",
                            "path": str(web_dir),
                            "filename": "webapp",
                        },
                    )

            manager.update_session(session_id, status="completed")
            yield _format_sse_event(
                "status", {"status": "completed", "message": "Task completed"}
            )

        except Exception as e:
            logger.error(f"Error executing task: {e}")
            manager.update_session(session_id, status="failed")
            yield _format_sse_event("error", {"message": str(e)})
            yield _format_sse_event("status", {"status": "failed", "message": str(e)})

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
) -> list[ArtifactInfo]:
    """List artifacts generated in the session."""
    manager = get_session_manager()
    sandbox_path = manager.get_sandbox_path(session_id)

    if sandbox_path is None:
        raise HTTPException(status_code=404, detail="Session not found or not started")

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


@session_router.get("/sessions/{session_id}/artifacts/{path:path}")
def download_artifact(
    session_id: str,
    path: str,
    user: User | None = Depends(current_user),
) -> Response:
    """Download a specific artifact file."""
    manager = get_session_manager()
    sandbox_path = manager.get_sandbox_path(session_id)

    if sandbox_path is None:
        raise HTTPException(status_code=404, detail="Session not found or not started")

    file_path = sandbox_path / path

    # Security check: ensure path doesn't escape sandbox
    try:
        file_path = file_path.resolve()
        sandbox_path_resolved = sandbox_path.resolve()
        if not str(file_path).startswith(str(sandbox_path_resolved)):
            raise HTTPException(status_code=403, detail="Access denied")
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
