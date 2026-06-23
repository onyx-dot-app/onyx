"""API endpoints for Glomi Forge sessions."""

import time
from collections.abc import Generator
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from onyx.auth.users import current_user
from onyx.background.celery.tasks.glomi_forge.tasks import enqueue_forge_session
from onyx.db.engine.sql_engine import get_session
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import ForgeArtifactType
from onyx.db.enums import GlomiForgeStatus
from onyx.db.glomi_forge import create_glomi_forge_session
from onyx.db.glomi_forge import fetch_forge_events_after
from onyx.db.glomi_forge import get_glomi_forge_session
from onyx.db.glomi_forge import update_status
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.glomi_forge.configs import ENABLE_GLOMI_FORGE
from onyx.glomi_forge.schemas.forge_spec import ForgeSpec
from onyx.glomi_forge.services.forge_spec_builder import ForgeSpecBuilder
from onyx.llm.factory import get_default_llm
from onyx.server.features.glomi_forge.sse import event_to_sse
from onyx.server.features.glomi_forge.sse import SSE_KEEPALIVE
from shared_configs.contextvars import get_current_tenant_id

router = APIRouter(prefix="/glomi-forge", tags=["glomi-forge"])

SSE_IDLE_LIMIT = 600
SSE_POLL_SECONDS = 1


class CreateSessionRequest(BaseModel):
    request: str
    artifact_type: str = ForgeArtifactType.LANDING_PAGE.value


class CreateSessionResponse(BaseModel):
    session_id: str
    status: str


class InstructionRequest(BaseModel):
    content: str


def _guard_enabled() -> None:
    if not ENABLE_GLOMI_FORGE:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "glomi_forge disabled")


def _parse_artifact_type(raw_artifact_type: str) -> ForgeArtifactType:
    try:
        return ForgeArtifactType(raw_artifact_type)
    except ValueError:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Unsupported artifact_type: {raw_artifact_type}",
        )


def _build_spec(request: str, artifact_type: ForgeArtifactType) -> ForgeSpec:
    return ForgeSpecBuilder(get_default_llm()).build(request, artifact_type)


def _get_existing_session(db_session: Session, session_id: UUID) -> object:
    session = get_glomi_forge_session(db_session, session_id)
    if session is None:
        raise OnyxError(OnyxErrorCode.BUILD_SESSION_NOT_FOUND, "session not found")
    return session


@router.post("/sessions")
def create_session(
    body: CreateSessionRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> CreateSessionResponse:
    _guard_enabled()
    artifact_type = _parse_artifact_type(body.artifact_type)
    spec = _build_spec(body.request, artifact_type)
    session = create_glomi_forge_session(
        db_session,
        user_id=user.id if user is not None else None,
        artifact_type=artifact_type,
        template_id="landing_page",
        spec=spec,
        title=spec.title,
    )
    enqueue_forge_session(session.id, get_current_tenant_id())
    return CreateSessionResponse(
        session_id=str(session.id),
        status=session.status.value,
    )


@router.get("/sessions/{session_id}")
def get_session_view(
    session_id: UUID,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> dict[str, object]:
    _guard_enabled()
    _ = user
    session = _get_existing_session(db_session, session_id)
    return {
        "session_id": str(session.id),
        "status": session.status.value,
        "preview_url": session.preview_url,
        "latest_output": session.latest_output,
        "last_error": session.last_error,
    }


@router.post("/sessions/{session_id}/terminate")
def terminate_session(
    session_id: UUID,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> dict[str, bool]:
    _guard_enabled()
    _ = user
    _get_existing_session(db_session, session_id)
    update_status(db_session, session_id, GlomiForgeStatus.TERMINATED)
    return {"ok": True}


@router.post("/sessions/{session_id}/instruction")
def send_instruction(
    session_id: UUID,
    body: InstructionRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> dict[str, bool]:
    _guard_enabled()
    _ = user
    _ = body
    _get_existing_session(db_session, session_id)
    enqueue_forge_session(session_id, get_current_tenant_id())
    return {"ok": True}


@router.get("/sessions/{session_id}/events")
def stream_events(
    session_id: UUID,
    user: User | None = Depends(current_user),
) -> StreamingResponse:
    _guard_enabled()
    _ = user

    def gen() -> Generator[str, None, None]:
        after_seq = 0
        idle_count = 0
        while idle_count < SSE_IDLE_LIMIT:
            with get_session_with_current_tenant() as db_session:
                rows = fetch_forge_events_after(db_session, session_id, after_seq)
                session = get_glomi_forge_session(db_session, session_id)

            if rows:
                for seq, event in rows:
                    after_seq = seq
                    yield event_to_sse(seq, event)
                idle_count = 0
            else:
                yield SSE_KEEPALIVE
                idle_count += 1

            if session is not None and session.status.is_terminal():
                return
            time.sleep(SSE_POLL_SECONDS)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
