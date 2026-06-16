from __future__ import annotations

from datetime import datetime
from datetime import timezone
from uuid import UUID
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import ChatRun
from onyx.db.models import ChatRunEvent

RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"


def next_event_seq(events: list[object]) -> int:
    if not events:
        return 0
    return max(int(getattr(event, "seq")) for event in events) + 1


def create_chat_run__no_commit(
    db_session: Session,
    chat_session_id: UUID,
    user_message_id: int,
    assistant_message_id: int,
    model_provider: str | None,
    model_name: str | None,
) -> ChatRun:
    run = ChatRun(
        id=uuid4(),
        chat_session_id=chat_session_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
        status=RUNNING,
        model_provider=model_provider,
        model_name=model_name,
    )
    db_session.add(run)
    db_session.flush()
    return run


def append_chat_run_event__no_commit(
    db_session: Session,
    run_id: UUID,
    packet_json: dict,
) -> ChatRunEvent:
    existing_events = list(
        db_session.scalars(
            select(ChatRunEvent).where(ChatRunEvent.run_id == run_id)
        ).all()
    )
    event = ChatRunEvent(
        run_id=run_id,
        seq=next_event_seq(existing_events),
        packet_json=packet_json,
    )
    db_session.add(event)
    db_session.flush()
    return event


def mark_chat_run_status__no_commit(
    db_session: Session,
    run_id: UUID,
    status: str,
    error_detail: str | None = None,
) -> None:
    run = db_session.get(ChatRun, run_id)
    if run is None:
        return

    now = datetime.now(timezone.utc)
    run.status = status
    run.error_detail = error_detail
    run.updated_at = now
    if status in {COMPLETED, FAILED, CANCELLED}:
        run.completed_at = now


def fetch_active_chat_run(
    db_session: Session,
    chat_session_id: UUID,
) -> ChatRun | None:
    return db_session.scalar(
        select(ChatRun)
        .where(ChatRun.chat_session_id == chat_session_id)
        .where(ChatRun.status == RUNNING)
        .order_by(ChatRun.created_at.desc())
    )


def fetch_chat_run_events_after(
    db_session: Session,
    run_id: UUID,
    after_seq: int | None,
) -> list[ChatRunEvent]:
    stmt = select(ChatRunEvent).where(ChatRunEvent.run_id == run_id)
    if after_seq is not None:
        stmt = stmt.where(ChatRunEvent.seq > after_seq)
    return list(db_session.scalars(stmt.order_by(ChatRunEvent.seq.asc())).all())
