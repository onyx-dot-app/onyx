"""Turn preparation reads each row once."""

from uuid import UUID, uuid4

from sqlalchemy import delete, text
from sqlalchemy.orm import Session

from onyx.agents.models import RunStatus
from onyx.configs.constants import DEFAULT_PERSONA_ID, MessageType
from onyx.db.chat import (
    CHAT_RESPONSE_LOCK_TIMEOUT_MS,
    CHAT_RESPONSE_STATEMENT_TIMEOUT_MS,
    configure_response_transaction__no_commit,
    get_chat_session_by_id,
    get_selected_branch,
    load_message_branch,
    reserve_chat_response_ids,
    selected_response_status_for_user,
)
from onyx.db.models import ChatMessage, ChatSession
from onyx.db.persona import get_default_behavior_persona
from onyx.server.query_and_chat.models import AUTO_PLACE_AFTER_LATEST_MESSAGE
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user


def _chat_with_response(
    db_session: Session,
    user_id: UUID | None,
    status: RunStatus,
    persona_id: int | None = None,
) -> tuple[ChatSession, ChatMessage, ChatMessage, ChatMessage]:
    """A chat with a root, a question and the selected response."""
    chat = ChatSession(
        id=uuid4(), user_id=user_id, persona_id=persona_id, description="reads"
    )
    db_session.add(chat)
    db_session.flush()
    root = ChatMessage(
        chat_session_id=chat.id,
        message="",
        token_count=0,
        message_type=MessageType.SYSTEM,
    )
    db_session.add(root)
    db_session.flush()
    question = ChatMessage(
        chat_session_id=chat.id,
        parent_message_id=root.id,
        message="question",
        token_count=1,
        message_type=MessageType.USER,
    )
    db_session.add(question)
    db_session.flush()
    response = ChatMessage(
        chat_session_id=chat.id,
        parent_message_id=question.id,
        message="answer",
        token_count=1,
        message_type=MessageType.ASSISTANT,
        response_status=status,
    )
    db_session.add(response)
    db_session.flush()
    root.latest_child_message_id = question.id
    question.latest_child_message_id = response.id
    db_session.flush()
    return chat, root, question, response


def _status_by_the_two_old_reads(
    db_session: Session, chat_session_id: UUID, user_id: UUID | None
) -> RunStatus | None:
    """What the send route read before: the session, then the selected branch."""
    try:
        get_chat_session_by_id(
            chat_session_id=chat_session_id, user_id=user_id, db_session=db_session
        )
    except ValueError:
        return None
    selected, _ = get_selected_branch(db_session, chat_session_id)
    return selected.response_status if selected is not None else None


def test_selected_response_status_is_one_read_with_the_session_checks(
    db_session: Session, executed_sql: list[str]
) -> None:
    owner = create_test_user(db_session, "turn-reads-owner")
    other = create_test_user(db_session, "turn-reads-other")
    try:
        chat, _, _, _ = _chat_with_response(db_session, owner.id, RunStatus.SUSPENDED)
        executed_sql.clear()
        assert (
            selected_response_status_for_user(db_session, chat.id, owner.id)
            == RunStatus.SUSPENDED
        )
        assert len(executed_sql) == 1
        assert selected_response_status_for_user(db_session, uuid4(), owner.id) is None

        # The same answer as the two old reads, for each owner, caller, status,
        # last message and deleted flag.
        for chat_owner in (owner.id, None):
            for status in (RunStatus.SUSPENDED, RunStatus.COMPLETE):
                for question_last in (False, True):
                    for deleted in (False, True):
                        chat, _, _, response = _chat_with_response(
                            db_session, chat_owner, status
                        )
                        if question_last:
                            follow_up = ChatMessage(
                                chat_session_id=chat.id,
                                parent_message_id=response.id,
                                message="next",
                                token_count=1,
                                message_type=MessageType.USER,
                            )
                            db_session.add(follow_up)
                            db_session.flush()
                            response.latest_child_message_id = follow_up.id
                        chat.deleted = deleted
                        db_session.flush()
                        for caller in (owner.id, other.id, None):
                            assert selected_response_status_for_user(
                                db_session, chat.id, caller
                            ) == _status_by_the_two_old_reads(
                                db_session, chat.id, caller
                            ), (chat_owner, status, question_last, deleted, caller)
    finally:
        db_session.rollback()
        delete_test_user(db_session, owner, other)
        db_session.commit()


def test_load_message_branch_reads_the_root_once(
    db_session: Session, executed_sql: list[str]
) -> None:
    try:
        chat, root, question, response = _chat_with_response(
            db_session, None, RunStatus.COMPLETE
        )
        db_session.expire_all()

        executed_sql.clear()
        history, parent = load_message_branch(
            chat.id, AUTO_PLACE_AFTER_LATEST_MESSAGE, db_session
        )

        assert [message.id for message in history] == [question.id, response.id]
        assert parent.id == response.id
        assert not [
            statement
            for statement in executed_sql
            if "parent_message_id IS NULL" in statement
        ]

        # The root is still the parent of a first message.
        history, parent = load_message_branch(chat.id, None, db_session)
        assert history == []
        assert parent.id == root.id
    finally:
        db_session.rollback()


def _delete_chat(db_session: Session, chat_id: UUID) -> None:
    """Removes a chat that a test committed."""
    db_session.rollback()
    db_session.execute(
        text(
            "UPDATE chat_message SET latest_child_message_id = NULL,"
            " parent_message_id = NULL WHERE chat_session_id = :id"
        ),
        {"id": chat_id},
    )
    db_session.execute(
        delete(ChatMessage).where(ChatMessage.chat_session_id == chat_id)
    )
    db_session.execute(delete(ChatSession).where(ChatSession.id == chat_id))
    db_session.commit()


def test_reserve_takes_the_parent_from_the_session(
    db_session: Session, executed_sql: list[str]
) -> None:
    chat, _, question, _ = _chat_with_response(db_session, None, RunStatus.COMPLETE)
    chat_id = chat.id
    try:
        executed_sql.clear()
        reserved = reserve_chat_response_ids(
            db_session, chat_id, question.id, ["model"]
        )

        assert question.latest_child_message_id == reserved[-1]
        # The parent is in the session, so no statement selects it.
        assert not [
            s
            for s in executed_sql
            if s.startswith("SELECT")
            and "FROM chat_message" in s
            and "chat_input" not in s
        ]
    finally:
        _delete_chat(db_session, chat_id)


def test_default_persona_comes_from_the_session_that_loaded_the_chat(
    db_session: Session, executed_sql: list[str]
) -> None:
    try:
        chat, _, _, _ = _chat_with_response(
            db_session, None, RunStatus.COMPLETE, persona_id=DEFAULT_PERSONA_ID
        )
        db_session.expire_all()
        loaded = get_chat_session_by_id(
            chat_session_id=chat.id,
            user_id=None,
            db_session=db_session,
            eager_load_persona=True,
        )

        executed_sql.clear()
        persona = get_default_behavior_persona(db_session)

        assert persona is loaded.persona
        assert executed_sql == []
    finally:
        db_session.rollback()


def test_response_transaction_sets_both_timeouts_in_one_statement(
    db_session: Session, executed_sql: list[str]
) -> None:
    try:
        executed_sql.clear()
        configure_response_transaction__no_commit(db_session)

        assert len(executed_sql) == 1
        for setting, expected_ms in (
            ("statement_timeout", CHAT_RESPONSE_STATEMENT_TIMEOUT_MS),
            ("lock_timeout", CHAT_RESPONSE_LOCK_TIMEOUT_MS),
        ):
            assert db_session.scalar(
                text(
                    "SELECT current_setting(:setting)::interval"
                    " = make_interval(secs => :ms / 1000.0)"
                ),
                {"setting": setting, "ms": expected_ms},
            )
    finally:
        db_session.rollback()
