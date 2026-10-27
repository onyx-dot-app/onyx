"""PostgreSQL serializes checkpoint ownership without changing transaction ownership."""

from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from onyx.agents.models import RunStatus
from onyx.chat.response_models import CheckpointBinding, ResponseCheckpoint
from onyx.configs.constants import MessageType
from onyx.db.chat_checkpoint import (
    check_checkpoint_owner__no_commit,
    claim_checkpoint__no_commit,
    interrupt_response__no_commit,
    publish_checkpoint__no_commit,
    release_checkpoint_claim__no_commit,
)
from onyx.db.enums import IncognitoRecordMode
from onyx.db.models import ChatMessage, ChatResponseCheckpoint, ChatSession


def test_checkpoint_publish_claim_release_and_finalize(db_session: Session) -> None:
    chat = ChatSession(id=uuid4(), description="checkpoint prefix probe")
    db_session.add(chat)
    db_session.flush()
    response = ChatMessage(
        chat_session_id=chat.id,
        message="",
        token_count=0,
        message_type=MessageType.ASSISTANT,
        response_status=RunStatus.RUNNING,
    )
    db_session.add(response)
    db_session.flush()
    checkpoint = ResponseCheckpoint(
        history_digest="history",
        response_digest="response",
        binding=CheckpointBinding(tenant_id="public", response_id=str(response.id)),
        revision=1,
        progress={},
        compaction_checkpoint=None,
        request_params=None,
        message_payloads=[],
        input_payloads=[],
    )
    assert (
        publish_checkpoint__no_commit(
            db_session, response.id, checkpoint, expected_ownership_version=None
        )
        == 1
    )
    assert response.response_status == RunStatus.SUSPENDED
    claim = claim_checkpoint__no_commit(db_session, response.id)
    assert claim is not None and claim.ownership_version == 2
    assert claim.data == checkpoint
    assert claim_checkpoint__no_commit(db_session, response.id) is None
    with pytest.raises(ValueError, match="ownership changed"):
        check_checkpoint_owner__no_commit(db_session, response.id, 1)
    check_checkpoint_owner__no_commit(db_session, response.id, 2)
    release_checkpoint_claim__no_commit(db_session, response.id, 2)
    db_session.flush()
    claim = claim_checkpoint__no_commit(db_session, response.id)
    assert claim is not None and claim.ownership_version == 3
    assert (
        publish_checkpoint__no_commit(
            db_session, response.id, checkpoint, expected_ownership_version=3
        )
        == 4
    )
    interrupt_response__no_commit(db_session, response.id, cancelled=True)
    db_session.flush()
    assert response.response_status == RunStatus.CANCELLED
    assert db_session.get(ChatResponseCheckpoint, response.id) is None
    with pytest.raises(ValueError, match="active response"):
        publish_checkpoint__no_commit(
            db_session, response.id, checkpoint, expected_ownership_version=None
        )
    db_session.rollback()


@pytest.fixture
def committed_response(db_session: Session) -> Generator[int, None, None]:
    chat = ChatSession(id=uuid4(), description="checkpoint ownership test")
    db_session.add(chat)
    db_session.flush()
    response = ChatMessage(
        chat_session_id=chat.id,
        message="",
        token_count=0,
        message_type=MessageType.ASSISTANT,
        response_status=RunStatus.RUNNING,
    )
    db_session.add(response)
    db_session.commit()
    try:
        yield response.id
    finally:
        db_session.rollback()
        db_session.delete(chat)
        db_session.commit()


def checkpoint_data(message_id: int) -> ResponseCheckpoint:
    return ResponseCheckpoint(
        history_digest="history",
        response_digest="response",
        binding=CheckpointBinding(tenant_id="public", response_id=str(message_id)),
        revision=1,
        progress={},
        compaction_checkpoint=None,
        request_params=None,
        message_payloads=[],
        input_payloads=[],
    )


def test_competing_claims_admit_one_owner(
    db_session: Session, committed_response: int
) -> None:
    message_id = committed_response
    publish_checkpoint__no_commit(
        db_session,
        message_id,
        checkpoint_data(message_id),
        expected_ownership_version=None,
    )
    db_session.commit()
    barrier = Barrier(2)
    bind = db_session.get_bind()

    def claim() -> int | None:
        with Session(bind=bind) as session:
            barrier.wait(timeout=5)
            claimed = claim_checkpoint__no_commit(session, message_id)
            session.commit()
            return claimed.ownership_version if claimed is not None else None

    with ThreadPoolExecutor(max_workers=2) as workers:
        claims = list(workers.map(lambda _: claim(), range(2)))
    assert claims.count(None) == 1
    assert claims.count(2) == 1
    with pytest.raises(ValueError, match="ownership changed"):
        publish_checkpoint__no_commit(
            db_session,
            message_id,
            checkpoint_data(message_id),
            expected_ownership_version=1,
        )
    db_session.rollback()
    with pytest.raises(ValueError, match="ownership changed"):
        release_checkpoint_claim__no_commit(db_session, message_id, 1)
    db_session.rollback()
    check_checkpoint_owner__no_commit(db_session, message_id, 2)


def test_failed_publication_and_claim_can_roll_back(
    db_session: Session, committed_response: int
) -> None:
    message_id = committed_response
    data = checkpoint_data(message_id)
    publish_checkpoint__no_commit(
        db_session, message_id, data, expected_ownership_version=None
    )
    db_session.rollback()
    assert db_session.get(ChatResponseCheckpoint, message_id) is None
    response = db_session.get(ChatMessage, message_id)
    assert response is not None and response.response_status == RunStatus.RUNNING
    publish_checkpoint__no_commit(
        db_session, message_id, data, expected_ownership_version=None
    )
    db_session.commit()
    assert claim_checkpoint__no_commit(db_session, message_id) is not None
    db_session.rollback()
    response = db_session.get(ChatMessage, message_id)
    assert response is not None and response.response_status == RunStatus.SUSPENDED
    row = db_session.get(ChatResponseCheckpoint, message_id)
    assert row is not None and row.ownership_version == 1


@pytest.mark.parametrize("cancelled", [False, True])
def test_lost_owner_finalization_removes_checkpoint(
    db_session: Session, committed_response: int, cancelled: bool
) -> None:
    message_id = committed_response
    publish_checkpoint__no_commit(
        db_session,
        message_id,
        checkpoint_data(message_id),
        expected_ownership_version=None,
    )
    interrupt_response__no_commit(db_session, message_id, cancelled=cancelled)
    db_session.commit()
    response = db_session.get(ChatMessage, message_id)
    assert response is not None
    assert response.response_status == (
        RunStatus.CANCELLED if cancelled else RunStatus.ERROR
    )
    assert (response.response_failure is None) == cancelled
    assert db_session.get(ChatResponseCheckpoint, message_id) is None
    assert claim_checkpoint__no_commit(db_session, message_id) is None
    with pytest.raises(ValueError, match="active response"):
        publish_checkpoint__no_commit(
            db_session,
            message_id,
            checkpoint_data(message_id),
            expected_ownership_version=None,
        )


def test_competing_publications_preserve_one_checkpoint(
    db_session: Session, committed_response: int
) -> None:
    message_id = committed_response
    barrier = Barrier(2)
    bind = db_session.get_bind()

    def publish(revision: int) -> int | None:
        with Session(bind=bind) as session:
            data = checkpoint_data(message_id).model_copy(update={"revision": revision})
            barrier.wait(timeout=5)
            try:
                publish_checkpoint__no_commit(
                    session, message_id, data, expected_ownership_version=None
                )
                session.commit()
                return revision
            except ValueError:
                session.rollback()
                return None

    with ThreadPoolExecutor(max_workers=2) as workers:
        published = list(workers.map(publish, [10, 20]))
    assert published.count(None) == 1
    saved = claim_checkpoint__no_commit(db_session, message_id)
    assert saved is not None
    assert saved.data.revision == next(
        value for value in published if value is not None
    )
    assert saved.ownership_version == 2


@pytest.mark.parametrize("existing_checkpoint", [False, True])
@pytest.mark.parametrize("rejection", ["content_free", "response_binding"])
def test_invalid_checkpoint_publication_leaves_state_unchanged(
    db_session: Session,
    committed_response: int,
    existing_checkpoint: bool,
    rejection: str,
) -> None:
    response = db_session.get(ChatMessage, committed_response)
    assert response is not None
    if rejection == "content_free":
        response.chat_session.incognito_record_mode = IncognitoRecordMode.USAGE_ONLY
    if existing_checkpoint:
        db_session.add(
            ChatResponseCheckpoint(
                chat_message_id=response.id, ownership_version=1, state={}
            )
        )
    db_session.commit()
    checkpoint = checkpoint_data(response.id)
    checkpoint.progress = {"private": "answer"}
    if rejection == "response_binding":
        checkpoint.binding = CheckpointBinding(
            tenant_id="public", response_id=str(response.id + 1)
        )
    statements: list[str] = []

    def capture(statement: str, **_event: object) -> None:
        statements.append(statement)

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", capture, named=True)
    try:
        expected_error = "Content-free" if rejection == "content_free" else "binding"
        with pytest.raises(ValueError, match=expected_error):
            publish_checkpoint__no_commit(
                db_session,
                response.id,
                checkpoint,
                expected_ownership_version=1 if existing_checkpoint else None,
            )
        db_session.flush()
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert not any(
        statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        for statement in statements
    )
    assert response.response_status == RunStatus.RUNNING
    saved = db_session.get(ChatResponseCheckpoint, response.id)
    if existing_checkpoint:
        assert saved is not None and saved.state == {}
        assert saved.ownership_version == 1
    else:
        assert saved is None
