"""DB operations for Glomi Forge sessions and events."""

import json
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import cast
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.enums import ForgeArtifactType
from onyx.db.enums import GlomiForgeStatus
from onyx.db.models import GlomiForgeEvent
from onyx.db.models import GlomiForgeSession
from onyx.glomi_forge.schemas.events import ForgeEvent
from onyx.glomi_forge.schemas.events import parse_builder_event
from onyx.glomi_forge.schemas.forge_session import ForgeError
from onyx.glomi_forge.schemas.forge_spec import ForgeSpec
from onyx.glomi_forge.schemas.output_manifest import OutputManifest
from onyx.glomi_forge.schemas.sandbox import PreviewInfo


def _dump_model(model: BaseModel) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(model.model_dump_json()))


def create_glomi_forge_session(
    db_session: Session,
    *,
    user_id: UUID | None,
    artifact_type: ForgeArtifactType,
    template_id: str,
    spec: ForgeSpec,
    title: str | None,
    parent_chat_session_id: UUID | None = None,
) -> GlomiForgeSession:
    session = GlomiForgeSession(
        user_id=user_id,
        parent_chat_session_id=parent_chat_session_id,
        artifact_type=artifact_type,
        template_id=template_id,
        title=title,
        status=GlomiForgeStatus.QUEUED,
        spec=_dump_model(spec),
    )
    db_session.add(session)
    db_session.commit()
    return session


def get_glomi_forge_session(
    db_session: Session,
    session_id: UUID,
) -> GlomiForgeSession | None:
    return db_session.scalar(
        select(GlomiForgeSession).where(GlomiForgeSession.id == session_id)
    )


def update_status(
    db_session: Session,
    session_id: UUID,
    status: GlomiForgeStatus,
    reason: str | None = None,
) -> None:
    session = get_glomi_forge_session(db_session, session_id)
    if session is None:
        return

    session.status = status
    if reason is not None:
        session.status_reason = reason
    if status.is_terminal():
        session.completed_at = datetime.now(timezone.utc)
    db_session.commit()


def attach_sandbox(
    db_session: Session,
    session_id: UUID,
    sandbox_id: str,
) -> None:
    session = get_glomi_forge_session(db_session, session_id)
    if session is None:
        return

    session.sandbox_id = sandbox_id
    db_session.commit()


def attach_builder(
    db_session: Session,
    session_id: UUID,
    builder_session_id: str,
) -> None:
    session = get_glomi_forge_session(db_session, session_id)
    if session is None:
        return

    session.builder_session_id = builder_session_id
    db_session.commit()


def set_preview(
    db_session: Session,
    session_id: UUID,
    preview: PreviewInfo,
) -> None:
    session = get_glomi_forge_session(db_session, session_id)
    if session is None:
        return

    session.preview_url = preview.url
    db_session.commit()


def set_output(
    db_session: Session,
    session_id: UUID,
    output: OutputManifest,
) -> None:
    session = get_glomi_forge_session(db_session, session_id)
    if session is None:
        return

    session.latest_output = _dump_model(output)
    db_session.commit()


def set_failed(
    db_session: Session,
    session_id: UUID,
    error: ForgeError,
) -> None:
    session = get_glomi_forge_session(db_session, session_id)
    if session is None:
        return

    session.status = GlomiForgeStatus.FAILED
    session.last_error = _dump_model(error)
    session.completed_at = datetime.now(timezone.utc)
    db_session.commit()


def append_build_event(
    db_session: Session,
    session_id: UUID,
    event: ForgeEvent,
) -> int:
    next_seq = (
        db_session.scalar(
            select(func.coalesce(func.max(GlomiForgeEvent.seq), 0)).where(
                GlomiForgeEvent.session_id == session_id
            )
        )
        or 0
    ) + 1
    db_session.add(
        GlomiForgeEvent(
            session_id=session_id,
            seq=next_seq,
            packet_json=_dump_model(event),
        )
    )
    db_session.commit()
    return next_seq


def fetch_forge_events_after(
    db_session: Session,
    session_id: UUID,
    after_seq: int,
) -> list[tuple[int, ForgeEvent]]:
    rows = db_session.scalars(
        select(GlomiForgeEvent)
        .where(
            GlomiForgeEvent.session_id == session_id,
            GlomiForgeEvent.seq > after_seq,
        )
        .order_by(GlomiForgeEvent.seq)
    ).all()

    return [
        (row.seq, parse_builder_event(cast(dict[str, object], row.packet_json)))
        for row in rows
    ]
