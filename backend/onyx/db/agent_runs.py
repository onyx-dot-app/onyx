"""Atomic run ownership. A claimed run is never replayed on another attempt."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select, tuple_, update
from sqlalchemy.orm import Session

from onyx.db.chat import get_chat_session_by_id
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import record_mode_persists_content
from onyx.db.models import AgentRun, ChatMessage, ChatSession, Persona, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

ACTIVE = ("queued", "running", "finishing")
TERMINAL = ("completed", "cancelled", "failed", "interrupted")


def create_runs(runs: list[AgentRun]) -> None:
    with get_session_with_current_tenant() as session:
        session.add_all(runs)
        session.commit()


def get_run(run_id: UUID) -> AgentRun:
    with get_session_with_current_tenant() as session:
        run = session.get(AgentRun, run_id)
        if run is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Unknown agent run")
        session.expunge(run)
        return run


def claim_run(run_id: UUID, attempt_id: UUID) -> bool:
    with get_session_with_current_tenant() as session:
        result = session.execute(
            update(AgentRun)
            .where(
                AgentRun.id == run_id,
                AgentRun.status == "queued",
                AgentRun.attempt_id.is_(None),
                AgentRun.cancel_requested.is_(False),
                AgentRun.expires_at > datetime.now(timezone.utc),
            )
            .values(
                status="running",
                attempt_id=attempt_id,
                updated_at=datetime.now(timezone.utc),
            )
            .returning(AgentRun.id)
        )
        changed = result.scalar_one_or_none() is not None
        session.commit()
        return changed


def heartbeat_run(run_id: UUID, attempt_id: UUID) -> bool:
    now = datetime.now(timezone.utc)
    with get_session_with_current_tenant() as session:
        result = session.execute(
            update(AgentRun)
            .where(
                AgentRun.id == run_id,
                AgentRun.attempt_id == attempt_id,
                AgentRun.status == "running",
                AgentRun.cancel_requested.is_(False),
                AgentRun.expires_at > now,
            )
            .values(updated_at=now)
            .returning(AgentRun.id)
        )
        changed = result.scalar_one_or_none() is not None
        session.commit()
        return changed


def require_owner(run_id: UUID, attempt_id: UUID) -> AgentRun:
    run = get_run(run_id)
    if (
        run.status != "running"
        or run.attempt_id != attempt_id
        or run.cancel_requested
        or run.expires_at <= datetime.now(timezone.utc)
    ):
        raise OnyxError(
            OnyxErrorCode.CONFLICT, "Agent execution no longer owns this run"
        )
    return run


def begin_finish(
    run_id: UUID,
    attempt_id: UUID | None,
    *,
    observed_updated_at: datetime | None = None,
) -> bool:
    now = datetime.now(timezone.utc)
    statement = (
        update(AgentRun)
        .where(
            AgentRun.id == run_id,
            AgentRun.attempt_id == attempt_id,
            AgentRun.status.in_(("running", "queued")),
        )
        .values(status="finishing", updated_at=now)
        .returning(AgentRun.id)
    )
    if observed_updated_at is not None:
        statement = statement.where(
            AgentRun.updated_at == observed_updated_at,
            or_(
                AgentRun.updated_at < now - timedelta(seconds=60),
                AgentRun.cancel_requested.is_(True),
                AgentRun.expires_at <= now,
            ),
        )
    with get_session_with_current_tenant() as session:
        changed = session.execute(statement).scalar_one_or_none() is not None
        session.commit()
        return changed


def _lock_run_for_completion(session: Session, run_id: UUID) -> AgentRun:
    run = session.get(AgentRun, run_id)
    if run is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Unknown agent run")
    # Serialize all model completions before changing any run row. Otherwise two
    # transactions can each observe the other model as unfinished and lose done.
    session.execute(
        select(ChatSession.id)
        .where(ChatSession.id == run.chat_session_id)
        .with_for_update()
    ).scalar_one()
    return session.execute(
        select(AgentRun)
        .where(AgentRun.id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()


def _complete_locked_run(session: Session, run: AgentRun, status: str) -> bool:
    run.status = status
    run.updated_at = datetime.now(timezone.utc)
    session.flush()
    remaining = session.scalar(
        select(AgentRun.id)
        .where(
            AgentRun.chat_session_id == run.chat_session_id,
            AgentRun.group_id == run.group_id,
            AgentRun.status.in_(ACTIVE),
        )
        .limit(1)
    )
    session.commit()
    return remaining is None


def complete_run(run_id: UUID, status: str) -> bool:
    """Finish once and return whether this transition completed the model group."""
    if status not in TERMINAL:
        raise ValueError("Invalid terminal agent status")
    with get_session_with_current_tenant() as session:
        run = _lock_run_for_completion(session, run_id)
        if run.status != "finishing":
            return False
        if run.cancel_requested:
            status = "cancelled"
        return _complete_locked_run(session, run, status)


def recover_stale_finish(run_id: UUID, observed_updated_at: datetime) -> bool | None:
    """Interrupt an abandoned finalizer without replaying any finalization effects.

    None means another process changed the run. Otherwise the result states
    whether recovery completed the group, allowing its stream to be closed.
    """
    with get_session_with_current_tenant() as session:
        run = _lock_run_for_completion(session, run_id)
        if (
            run.status != "finishing"
            or run.updated_at != observed_updated_at
            or run.updated_at > datetime.now(timezone.utc) - timedelta(minutes=5)
        ):
            return None
        return _complete_locked_run(
            session, run, "cancelled" if run.cancel_requested else "interrupted"
        )


def cancel_session_runs(session_id: UUID) -> None:
    with get_session_with_current_tenant() as session:
        session.execute(
            update(AgentRun)
            .where(
                AgentRun.chat_session_id == session_id,
                AgentRun.status.in_(ACTIVE),
            )
            .values(cancel_requested=True)
        )
        session.commit()


def latest_group(session_id: UUID) -> int | None:
    with get_session_with_current_tenant() as session:
        return session.scalar(
            select(AgentRun.group_id)
            .where(
                AgentRun.chat_session_id == session_id,
            )
            .order_by(AgentRun.created_at.desc())
            .limit(1)
        )


def recovery_candidates() -> list[AgentRun]:
    now = datetime.now(timezone.utc)
    with get_session_with_current_tenant() as session:
        runs = list(
            session.scalars(
                select(AgentRun)
                .where(
                    or_(
                        and_(
                            AgentRun.status.in_(("queued", "running")),
                            or_(
                                AgentRun.updated_at < now - timedelta(seconds=60),
                                AgentRun.expires_at <= now,
                                AgentRun.cancel_requested.is_(True),
                            ),
                        ),
                        and_(
                            AgentRun.status == "finishing",
                            AgentRun.updated_at < now - timedelta(minutes=5),
                        ),
                    )
                )
                # Existing queue backlog must not hide abandoned active runs.
                .order_by(
                    case((AgentRun.status == "queued", 1), else_=0),
                    AgentRun.updated_at,
                )
                .limit(100)
            )
        )
        session.expunge_all()
        return runs


def load_host_records(session_id: UUID, user_id: UUID) -> tuple[User, Persona]:
    with get_session_with_current_tenant() as session:
        user = session.get(User, user_id)
        if user is None:
            from onyx.auth.users import get_anonymous_user

            user = get_anonymous_user()
            if user.id != user_id:
                raise ValueError("Agent user no longer exists")
        chat = get_chat_session_by_id(
            session_id, user_id, session, eager_load_persona=True
        )
        persona = chat.persona
        session.expunge_all()
        return user, persona


def load_message(message_id: int) -> ChatMessage:
    with get_session_with_current_tenant() as session:
        message = session.get(ChatMessage, message_id)
        if message is None:
            raise ValueError("Agent message no longer exists")
        session.expunge(message)
        return message


def save_failure(message_id: int, text: str) -> None:
    with get_session_with_current_tenant() as session:
        message = session.get(ChatMessage, message_id)
        if message is not None:
            message.message = text
            message.error = text
            message.token_count = 0
            session.commit()


def claim_operation(run_id: UUID, attempt_id: UUID, sequence: int) -> AgentRun:
    if sequence < 1:
        raise ValueError("Agent callback sequence must be positive")
    now = datetime.now(timezone.utc)
    with get_session_with_current_tenant() as session:
        result = session.execute(
            update(AgentRun)
            .where(
                AgentRun.id == run_id,
                AgentRun.attempt_id == attempt_id,
                AgentRun.status == "running",
                AgentRun.last_sequence == sequence - 1,
                AgentRun.cancel_requested.is_(False),
                AgentRun.expires_at > now,
            )
            .values(last_sequence=sequence, updated_at=now)
            .returning(AgentRun.id)
        )
        if result.scalar_one_or_none() is None:
            session.rollback()
            raise OnyxError(OnyxErrorCode.CONFLICT, "Duplicate or stale agent callback")
        session.commit()
    return require_owner(run_id, attempt_id)


@dataclass(frozen=True)
class PendingStreamClosure:
    session_id: UUID
    group_id: int
    content_free: bool
    interrupted: bool


def pending_stream_closures() -> list[PendingStreamClosure]:
    """Find completed model groups whose transient completion was not confirmed."""
    with get_session_with_current_tenant() as session:
        rows = session.execute(
            select(
                AgentRun.chat_session_id,
                AgentRun.group_id,
                ChatSession.incognito_record_mode,
                func.bool_or(AgentRun.status == "interrupted"),
            )
            .join(ChatSession, ChatSession.id == AgentRun.chat_session_id)
            .where(AgentRun.stream_closed.is_(False))
            .group_by(
                AgentRun.chat_session_id,
                AgentRun.group_id,
                ChatSession.incognito_record_mode,
            )
            .having(func.bool_and(AgentRun.status.in_(TERMINAL)))
            .order_by(func.min(AgentRun.updated_at))
            .limit(100)
        )
        return [
            PendingStreamClosure(
                session_id=session_id,
                group_id=group_id,
                content_free=not record_mode_persists_content(mode),
                interrupted=interrupted,
            )
            for session_id, group_id, mode, interrupted in rows
        ]


def mark_group_stream_closed(session_id: UUID, group_id: int) -> None:
    """Acknowledge completion only after Redis and processing-status updates succeed."""
    with get_session_with_current_tenant() as session:
        session.execute(
            update(AgentRun)
            .where(
                AgentRun.chat_session_id == session_id,
                AgentRun.group_id == group_id,
                AgentRun.status.in_(TERMINAL),
            )
            .values(stream_closed=True)
        )
        session.commit()


def list_session_runs(session_id: UUID) -> list[AgentRun]:
    with get_session_with_current_tenant() as session:
        runs = list(
            session.scalars(
                select(AgentRun).where(AgentRun.chat_session_id == session_id)
            )
        )
        session.expunge_all()
        return runs


def heartbeat_finalizer(run_id: UUID, attempt_id: UUID | None) -> bool:
    """Keep a live finalizer from being mistaken for a crashed API process."""
    with get_session_with_current_tenant() as session:
        result = session.execute(
            update(AgentRun)
            .where(
                AgentRun.id == run_id,
                AgentRun.attempt_id == attempt_id,
                AgentRun.status == "finishing",
            )
            .values(updated_at=datetime.now(timezone.utc))
            .returning(AgentRun.id)
        )
        changed = result.scalar_one_or_none() is not None
        session.commit()
        return changed


def heartbeat_runs(attempts: list[tuple[UUID, UUID]]) -> list[UUID]:
    """Renew one worker's tenant-scoped leases and return unavailable run IDs."""
    if not attempts:
        return []
    now = datetime.now(timezone.utc)
    with get_session_with_current_tenant() as session:
        renewed = set(
            session.scalars(
                update(AgentRun)
                .where(
                    tuple_(AgentRun.id, AgentRun.attempt_id).in_(attempts),
                    AgentRun.status == "running",
                    AgentRun.cancel_requested.is_(False),
                    AgentRun.expires_at > now,
                )
                .values(updated_at=now)
                .returning(AgentRun.id)
            )
        )
        session.commit()
        return [
            run_id
            for run_id in dict.fromkeys(run_id for run_id, _ in attempts)
            if run_id not in renewed
        ]


def any_runs_exist(run_ids: list[UUID]) -> bool:
    """Resolve an uncertain dispatch commit before releasing its processing fence."""
    if not run_ids:
        return False
    with get_session_with_current_tenant() as session:
        return (
            session.scalar(select(AgentRun.id).where(AgentRun.id.in_(run_ids)).limit(1))
            is not None
        )
