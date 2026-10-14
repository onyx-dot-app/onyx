"""Conditional checkpoint transitions. Callers own transactions."""

from pydantic import BaseModel, JsonValue, TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.agents.execution_records import RunFailure, RunFailureKind, RunStatus
from onyx.chat.models import ResponseCheckpoint
from onyx.db.chat_response import (
    configure_response_transaction__no_commit,
    finish_checkpoint__no_commit,
)
from onyx.db.models import ChatMessage, ChatResponseCheckpoint

_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


class SavedCheckpoint(BaseModel):
    ownership_version: int
    data: ResponseCheckpoint


def _lock_response(session: Session, message_id: int) -> ChatMessage:
    response = session.scalar(
        select(ChatMessage)
        .where(ChatMessage.id == message_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if response is None:
        raise ValueError("Response is unavailable")
    return response


def publish_checkpoint__no_commit(
    session: Session,
    message_id: int,
    data: ResponseCheckpoint,
    *,
    expected_ownership_version: int | None,
) -> int:
    response = _lock_response(session, message_id)
    if response.response_status is None or response.response_status.is_terminal:
        raise ValueError("Only an active response can pause")
    row = session.get(ChatResponseCheckpoint, message_id, populate_existing=True)
    if row is None:
        if expected_ownership_version is not None:
            raise ValueError("Checkpoint was removed")
        row = ChatResponseCheckpoint(
            chat_message_id=message_id, ownership_version=1, state={}
        )
        session.add(row)
    else:
        if (
            expected_ownership_version != row.ownership_version
            or response.response_status != RunStatus.RUNNING
        ):
            raise ValueError("Checkpoint ownership changed")
        row.ownership_version += 1
    row.state = _JSON_OBJECT.validate_python(data.model_dump(mode="json"))
    response.response_status = RunStatus.SUSPENDED
    session.flush()
    return row.ownership_version


def claim_checkpoint__no_commit(
    session: Session, message_id: int
) -> SavedCheckpoint | None:
    response = _lock_response(session, message_id)
    row = session.get(ChatResponseCheckpoint, message_id, populate_existing=True)
    if row is None or response.response_status != RunStatus.SUSPENDED:
        return None
    row.ownership_version += 1
    response.response_status = RunStatus.RUNNING
    session.flush()
    return SavedCheckpoint(
        ownership_version=row.ownership_version,
        data=ResponseCheckpoint.model_validate(row.state),
    )


def check_checkpoint_owner__no_commit(
    session: Session, message_id: int, ownership_version: int | None
) -> None:
    configure_response_transaction__no_commit(session)
    response = _lock_response(session, message_id)
    row = session.get(ChatResponseCheckpoint, message_id, populate_existing=True)
    if (row is None) != (ownership_version is None) or (
        row is not None and row.ownership_version != ownership_version
    ):
        raise ValueError("Response ownership changed")
    if ownership_version is not None and response.response_status != RunStatus.RUNNING:
        raise ValueError("Response is no longer owned by this runner")


def release_checkpoint_claim__no_commit(
    session: Session, message_id: int, ownership_version: int
) -> None:
    """Undo a failed reconstruction only before resumed execution starts."""
    check_checkpoint_owner__no_commit(session, message_id, ownership_version)
    response = session.get(ChatMessage, message_id)
    if response is None:
        raise ValueError("Response is unavailable")
    response.response_status = RunStatus.SUSPENDED


def interrupt_response__no_commit(
    session: Session, message_id: int, *, cancelled: bool = False
) -> None:
    """Caller holds the response's cache lock and has verified that no owner remains."""
    response = _lock_response(session, message_id)
    if response.response_status is None or response.response_status.is_terminal:
        return
    response.response_status = RunStatus.CANCELLED if cancelled else RunStatus.ERROR
    if not cancelled:
        response.response_failure = RunFailure(
            kind=RunFailureKind.EXECUTION,
            message="The response owner stopped reporting progress",
        )
    finish_checkpoint__no_commit(session, message_id)
