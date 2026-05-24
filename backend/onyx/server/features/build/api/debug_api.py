"""Dev/debug-only endpoints for the build/craft feature.

Gated by the ``ENABLE_OPENCODE_DEBUGGING`` env var — when false, every
endpoint here 404s regardless of auth. This keeps the surface gone in
prod rather than just hidden in the UI.

The one endpoint right now is the opencode pod log streamer, used by the
FE debug button to tail the user's sandbox pod logs in real time.
"""

from collections.abc import Generator

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.enums import SandboxStatus
from onyx.db.models import User
from onyx.server.features.build.configs import ENABLE_OPENCODE_DEBUGGING
from onyx.server.features.build.db.sandbox import get_sandbox_by_user_id
from onyx.server.features.build.sandbox.base import get_sandbox_manager
from onyx.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter()


def _require_debug_enabled() -> None:
    """Return 404 (not 403) when debugging is off — we want the endpoint to
    look like it doesn't exist, not "you're not allowed". This makes
    accidental leaks in prod harmless beyond a 404 in logs."""
    if not ENABLE_OPENCODE_DEBUGGING:
        raise HTTPException(status_code=404, detail="Not Found")


@router.get("/debug/opencode-logs/stream")
def stream_opencode_logs(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
    _gate: None = Depends(_require_debug_enabled),
) -> StreamingResponse:
    """Server-Sent Events stream of the user's sandbox pod's
    ``sandbox`` (opencode-serve) container logs, following live.

    Each event is a single JSON object ``{"line": "..."}`` so the FE can
    extend the shape later without renegotiating the stream format.
    Closes cleanly on client disconnect (GeneratorExit) — the underlying
    kubernetes-client log stream is generator-based and stops on close.
    """
    sandbox = get_sandbox_by_user_id(db_session, user.id)
    if sandbox is None or sandbox.status != SandboxStatus.RUNNING:
        raise HTTPException(
            status_code=409,
            detail="No running sandbox to tail logs from",
        )

    sandbox_manager = get_sandbox_manager()
    # Only the K8s manager exposes pod logs — guard so other backends
    # (docker dev) return a clean error rather than blowing up on attribute
    # access.
    stream_fn = getattr(sandbox_manager, "stream_pod_logs", None)
    if stream_fn is None:
        raise HTTPException(
            status_code=501,
            detail="Pod log streaming is only available on the Kubernetes sandbox backend",
        )

    def sse_generator() -> Generator[str, None, None]:
        events_yielded = 0
        try:
            for line in stream_fn(sandbox.id):
                events_yielded += 1
                # SSE: one event per line, JSON-wrapped for forward compat.
                # Replace embedded newlines so they don't terminate the SSE
                # frame mid-event (lines from kubectl can already be broken
                # but defensive is cheaper than debugging).
                safe = line.replace("\r", "").replace("\n", "\\n")
                yield f'event: log\ndata: {{"line":"{_escape(safe)}"}}\n\n'
        except GeneratorExit:
            logger.info(
                "Debug log stream closed by client after %d lines (sandbox=%s)",
                events_yielded,
                sandbox.id,
            )
            raise
        except Exception as e:  # noqa: BLE001 — never let a tail crash the api
            logger.exception(
                "Debug log stream errored for sandbox %s after %d lines: %s",
                sandbox.id,
                events_yielded,
                e,
            )
            yield f'event: error\ndata: {{"message":"{_escape(str(e))}"}}\n\n'

    return StreamingResponse(
        sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _escape(s: str) -> str:
    """Minimal JSON string escape — we're hand-building the event payload
    because the value is a single field and we want to avoid the overhead
    of importing json.dumps inside the tight per-line loop."""
    return s.replace("\\", "\\\\").replace('"', '\\"')
