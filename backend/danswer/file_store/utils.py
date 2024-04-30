from typing import cast
from uuid import UUID

from sqlalchemy.orm import Session

from danswer.db.models import ChatMessage
from danswer.file_store.file_store import get_default_file_store
from danswer.file_store.models import InMemoryChatFile
from danswer.utils.threadpool_concurrency import run_functions_tuples_in_parallel


def build_chat_file_name(file_id: UUID | str) -> str:
    return f"chat__{file_id}"


def load_chat_file(file_id: UUID, db_session: Session) -> InMemoryChatFile:
    file_io = get_default_file_store(db_session).read_file(
        build_chat_file_name(file_id), mode="b"
    )
    return InMemoryChatFile(file_id=file_id, content=file_io.read())


def load_all_chat_files(
    chat_messages: list[ChatMessage], new_file_ids: list[UUID], db_session: Session
) -> list[InMemoryChatFile]:
    file_ids_for_history = []
    for chat_message in chat_messages:
        if chat_message.files:
            file_ids_for_history.extend([file["id"] for file in chat_message.files])

    files = cast(
        list[InMemoryChatFile],
        run_functions_tuples_in_parallel(
            [
                (load_chat_file, (file_id, db_session))
                for file_id in new_file_ids + file_ids_for_history
            ]
        ),
    )
    return files
