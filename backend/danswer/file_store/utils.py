from collections.abc import Callable
from io import BytesIO
from typing import Any
from typing import cast
from uuid import uuid4

import requests
from sqlalchemy.orm import Session

from danswer.configs.constants import FileOrigin
from danswer.db.engine import get_session_with_tenant
from danswer.db.models import ChatMessage
from danswer.file_store.file_store import get_default_file_store
from danswer.file_store.models import FileDescriptor
from danswer.file_store.models import InMemoryChatFile
from danswer.utils.threadpool_concurrency import run_functions_tuples_in_parallel
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


def load_chat_file(
    file_descriptor: FileDescriptor, db_session: Session
) -> InMemoryChatFile:
    file_io = get_default_file_store(db_session).read_file(
        file_descriptor["id"], mode="b"
    )
    return InMemoryChatFile(
        file_id=file_descriptor["id"],
        content=file_io.read(),
        file_type=file_descriptor["type"],
        filename=file_descriptor.get("name"),
    )


def load_all_chat_files(
    chat_messages: list[ChatMessage],
    file_descriptors: list[FileDescriptor],
    db_session: Session,
) -> list[InMemoryChatFile]:
    file_descriptors_for_history: list[FileDescriptor] = []
    for chat_message in chat_messages:
        if chat_message.files:
            file_descriptors_for_history.extend(chat_message.files)

    files = cast(
        list[InMemoryChatFile],
        run_functions_tuples_in_parallel(
            [
                (load_chat_file, (file, db_session))
                for file in file_descriptors + file_descriptors_for_history
            ]
        ),
    )
    return files


def save_file_from_url(url: str, tenant_id: str) -> str:
    """NOTE: using multiple sessions here, since this is often called
    using multithreading. In practice, sharing a session has resulted in
    weird errors."""
    with get_session_with_tenant(tenant_id) as db_session:
        response = requests.get(url)
        response.raise_for_status()

        unique_id = str(uuid4())

        file_io = BytesIO(response.content)
        file_store = get_default_file_store(db_session)
        file_store.save_file(
            file_name=unique_id,
            content=file_io,
            display_name="GeneratedImage",
            file_origin=FileOrigin.CHAT_IMAGE_GEN,
            file_type="image/png;base64",
        )
        return unique_id


def save_files_from_urls(urls: list[str]) -> list[str]:
    tenant_id = CURRENT_TENANT_ID_CONTEXTVAR.get()

    funcs: list[tuple[Callable[..., Any], tuple[Any, ...]]] = [
        (save_file_from_url, (url, tenant_id)) for url in urls
    ]
    # Must pass in tenant_id here, since this is called by multithreading
    return run_functions_tuples_in_parallel(funcs)
