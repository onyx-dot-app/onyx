"""Conditional checkpoint transitions. Callers own transactions."""

from pydantic import JsonValue, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.agents.models import RunFailure, RunFailureKind, RunStatus
from onyx.chat.models import ChatFeatureState, ResponseCheckpoint, SavedCheckpoint
from onyx.db.approval_request import (
    close_pending_approval_requests__no_commit,
    responses_waiting_for_approval,
)
from onyx.db.chat import configure_response_transaction__no_commit
from onyx.db.chat_response import (
    finish_checkpoint__no_commit,
)
from onyx.db.enums import ApprovalDecision, record_mode_persists_content
from onyx.db.models import ChatMessage, ChatResponseCheckpoint
from onyx.utils.logger import setup_logger

logger = setup_logger()
_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


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
    if data.binding.response_id != str(message_id):
        raise ValueError("Checkpoint binding does not match its response")
    response = _lock_response(session, message_id)
    if not record_mode_persists_content(response.chat_session.incognito_record_mode):
        raise ValueError("Content-free responses cannot store execution checkpoints")
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


def read_checkpoint(session: Session, message_id: int) -> ResponseCheckpoint | None:
    row = session.get(ChatResponseCheckpoint, message_id)
    return ResponseCheckpoint.model_validate(row.state) if row is not None else None


def check_checkpoint_owner__no_commit(
    session: Session, message_id: int, ownership_version: int | None
) -> None:
    """Check the checkpoint version; callers enforce the live cache ownership lease.

    Initial executions may repeat terminal saves for lifecycle and display storage.
    """
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
    session: Session,
    message_id: int,
    *,
    cancelled: bool = False,
    failure: RunFailure | None = None,
    running_only: bool = False,
) -> list[str] | None:
    """Caller holds the response's cache lock and has verified that no owner remains.

    A cancelled response keeps `failure`, the reason its Stop gave, if any; a
    failed one keeps `failure`, or says that its owner stopped. Its approval
    requests end, since no call waits for them anymore. With `running_only`, a
    parked response stays as it is. Returns the file IDs of the dumps of its
    parked programs, which the caller deletes after commit; None when the
    response did not end here.
    """
    response = _lock_response(session, message_id)
    if (
        response.response_status is None
        or response.response_status.is_terminal
        or (running_only and response.response_status != RunStatus.RUNNING)
    ):
        return None
    row = session.get(ChatResponseCheckpoint, message_id)
    dumps: list[str] = []
    if row is not None:
        try:
            feature_state = ResponseCheckpoint.model_validate(row.state).progress.get(
                "feature_state"
            )
            # Only chat agents run programs.
            if (
                isinstance(feature_state, dict)
                and feature_state.get("kind")
                == ChatFeatureState.model_fields["kind"].default
            ):
                dumps = [
                    file_id
                    for cell in ChatFeatureState.model_validate(
                        feature_state
                    ).code_cells
                    if (file_id := cell.program.dump.file_id) is not None
                ]
        except ValidationError:
            logger.exception("Could not read the parked programs of a response")
    close_pending_approval_requests__no_commit(
        session, ApprovalDecision.EXPIRED, None, chat_message_ids=[message_id]
    )
    response.response_status = RunStatus.CANCELLED if cancelled else RunStatus.ERROR
    response.response_failure = (
        failure
        if cancelled
        else failure
        or RunFailure(
            kind=RunFailureKind.EXECUTION,
            message="The response owner stopped reporting progress",
        )
    )
    finish_checkpoint__no_commit(session, message_id)
    return dumps


def resumable_parked_runs(session: Session, parked: dict[int, str]) -> dict[int, str]:
    """The parked runs, by response ID with their agent IDs, whose waits all
    ended: no request of the response waits and no foreground child run that
    its checkpoint waits for is unfinished. `parked` gives the runs whose other
    waits ended; their parked foreground children are added."""
    parked = dict(parked)
    waiting: set[int] = set()
    unread = list(parked)
    while unread:
        children: dict[int, list[int]] = {
            message_id: [int(child_id) for child_id in child_ids]
            for message_id, child_ids in session.execute(
                select(
                    ChatResponseCheckpoint.chat_message_id,
                    ChatResponseCheckpoint.state["progress"]["child_run_ids"],
                ).where(ChatResponseCheckpoint.chat_message_id.in_(unread))
            )
            if child_ids
        }
        unread = []
        child_rows = (
            session.execute(
                select(
                    ChatMessage.id,
                    ChatMessage.chat_session_id,
                    ChatMessage.response_status,
                ).where(
                    ChatMessage.id.in_(
                        [
                            child
                            for child_ids in children.values()
                            for child in child_ids
                        ]
                    )
                )
            ).all()
            if children
            else []
        )
        rows = {row.id: row for row in child_rows}
        for parent_id, child_ids in children.items():
            for child_id in child_ids:
                row = rows.get(child_id)
                if row is None or row.response_status is None:
                    continue
                if not row.response_status.is_terminal:
                    waiting.add(parent_id)
                if (
                    row.response_status == RunStatus.SUSPENDED
                    and child_id not in parked
                ):
                    parked[child_id] = str(row.chat_session_id)
                    unread.append(child_id)
    if parked:
        waiting |= responses_waiting_for_approval(session, parked)
    return {
        response_id: agent_id
        for response_id, agent_id in parked.items()
        if response_id not in waiting
    }
