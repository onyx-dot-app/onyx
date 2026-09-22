"""Status polling preserves branch identities without reading conversation payloads."""

from uuid import uuid4

from sqlalchemy import event
from sqlalchemy.orm import Session

from onyx.agents.transcript import RunStatus
from onyx.configs.constants import MessageType
from onyx.db.chat_checkpoint import read_response_status__no_commit
from onyx.db.models import ChatMessage, ChatSession, ToolCall


def test_response_status_reads_only_identity_and_status(db_session: Session) -> None:
    root_session = ChatSession(id=uuid4(), description="status test")
    db_session.add(root_session)
    db_session.flush()
    root = ChatMessage(
        chat_session_id=root_session.id,
        message="large response content",
        token_count=3,
        message_type=MessageType.ASSISTANT,
        run_id=str(uuid4()),
        response_status=RunStatus.RUNNING,
    )
    db_session.add(root)
    db_session.flush()
    invocation = ToolCall(
        chat_session_id=root_session.id,
        parent_chat_message_id=root.id,
        turn_number=0,
        tool_call_id="research",
        tool_name="research",
        tool_call_arguments={"question": "large tool arguments"},
        tool_call_tokens=3,
    )
    child_session = ChatSession(
        id=uuid4(), spawned_by_message_id=root.id, agent_name="research"
    )
    db_session.add_all([invocation, child_session])
    db_session.flush()
    question = ChatMessage(
        chat_session_id=child_session.id,
        invoking_tool_call_id=invocation.id,
        message="research question",
        token_count=2,
        message_type=MessageType.USER,
    )
    db_session.add(question)
    db_session.flush()
    child = ChatMessage(
        chat_session_id=child_session.id,
        parent_message_id=question.id,
        message="large child response",
        token_count=3,
        message_type=MessageType.ASSISTANT,
        run_id=str(uuid4()),
        response_status=RunStatus.SUSPENDED,
    )
    db_session.add(child)
    db_session.flush()
    root_id, child_id = root.id, child.id
    root_run_id, child_run_id = root.run_id, child.run_id
    root_session_id = root_session.id
    assert root_run_id is not None and child_run_id is not None
    db_session.expunge_all()
    statements: list[str] = []

    def capture_statement(statement: str, **_event: object) -> None:
        # SQLAlchemy supplies unused connection, cursor, and execution parameters.
        statements.append(statement)

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", capture_statement, named=True)
    try:
        root_status = read_response_status__no_commit(db_session, root_run_id)
        child_status = read_response_status__no_commit(db_session, child_run_id)
        archived_status = read_response_status__no_commit(db_session, str(child_id))
        missing = read_response_status__no_commit(db_session, str(uuid4()))
        assert root_status is not None
        assert root_status.message_id == root_id
        assert root_status.root_message_id == root_id
        assert root_status.parent_agent_id is None
        assert root_status.status == RunStatus.RUNNING
        assert child_status is not None
        assert child_status.message_id == child_id
        assert child_status.root_message_id == root_id
        assert child_status.root_session_id == root_session_id
        assert child_status.parent_agent_id == str(root_session_id)
        assert child_status.status == RunStatus.SUSPENDED
        assert archived_status == child_status
        assert missing is None
        assert len(statements) == 6
        sql = "\n".join(statements).lower()
        for forbidden in (
            "chat_response_item",
            "tool_call.result",
            "tool_call.tool_call_arguments",
            "chat_message.message,",
            "chat_message.reasoning_tokens",
            "restoration_config",
        ):
            assert forbidden not in sql
    finally:
        event.remove(engine, "before_cursor_execute", capture_statement)
        db_session.rollback()
