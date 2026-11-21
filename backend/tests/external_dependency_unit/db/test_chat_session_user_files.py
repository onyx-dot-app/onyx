"""The uploads of a chat (`db/chat.py` get_chat_session_user_files) when its
messages hold old or broken file descriptors."""

from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from onyx.configs.constants import MessageType
from onyx.db.chat import get_chat_session_user_files
from onyx.db.models import ChatMessage, ChatSession, UserFile
from tests.external_dependency_unit.conftest import MakeTestUser


def _user_message(db_session: Session, chat_session_id: UUID, files_sql: str) -> None:
    """A user message whose `files` column is the SQL expression `files_sql`."""
    message = ChatMessage(
        chat_session_id=chat_session_id,
        message="question",
        token_count=0,
        message_type=MessageType.USER,
    )
    db_session.add(message)
    db_session.flush()
    db_session.execute(
        text(f"UPDATE chat_message SET files = {files_sql} WHERE id = :id"),
        {"id": message.id},
    )


def test_old_and_broken_descriptors_are_skipped(
    db_session: Session, make_test_user: MakeTestUser
) -> None:
    user = make_test_user("chat-session-user-files")
    chat_session = ChatSession(id=uuid4(), user_id=user.id)
    first, second = (
        UserFile(
            id=uuid4(),
            user_id=user.id,
            file_id=f"file-{uuid4()}",
            name=name,
            file_type="text/plain",
        )
        for name in ("first.txt", "second.txt")
    )
    db_session.add_all([chat_session, first, second])
    db_session.flush()
    deleted_id = uuid4()

    # Integer IDs from before user files had UUID keys, as numbers and text.
    _user_message(
        db_session,
        chat_session.id,
        """'[{"id": "a", "type": "document", "user_file_id": 42},
             {"id": "b", "type": "document", "user_file_id": "42"}]'::jsonb""",
    )
    _user_message(db_session, chat_session.id, "'null'::jsonb")
    _user_message(db_session, chat_session.id, "NULL")
    _user_message(db_session, chat_session.id, """'{"user_file_id": 1}'::jsonb""")
    _user_message(
        db_session,
        chat_session.id,
        f"""'[{{"id": "c", "user_file_id": "not-a-uuid"}},
             {{"id": "d", "user_file_id": "{str(deleted_id)[:-1]}g"}},
             {{"id": "e", "user_file_id": "{deleted_id}"}},
             {{"id": "f", "user_file_id": "{second.id}"}},
             "a string", 7, null,
             {{"id": "g"}}]'::jsonb""",
    )
    _user_message(
        db_session,
        chat_session.id,
        f"""'[{{"id": "h", "user_file_id": "{str(first.id).upper()}"}},
             {{"id": "i", "user_file_id": "{second.id}"}}]'::jsonb""",
    )

    assert [
        user_file.id
        for user_file in get_chat_session_user_files(chat_session.id, db_session)
    ] == [second.id, first.id]
    db_session.rollback()
