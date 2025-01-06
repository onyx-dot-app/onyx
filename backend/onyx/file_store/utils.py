import base64
from collections.abc import Callable
from io import BytesIO
from typing import cast
from uuid import uuid4

import requests
from sqlalchemy.orm import Session

from onyx.configs.constants import FileOrigin
from onyx.db.engine import get_session_with_tenant
from onyx.db.models import ChatMessage
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.models import FileDescriptor
from onyx.file_store.models import InMemoryChatFile
from onyx.utils.b64 import get_image_type
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel


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


def save_file_from_base64(base64_string: str, tenant_id: str) -> str:
    with get_session_with_tenant(tenant_id) as db_session:
        unique_id = str(uuid4())
        file_store = get_default_file_store(db_session)
        file_store.save_file(
            file_name=unique_id,
            content=BytesIO(base64.b64decode(base64_string)),
            display_name="GeneratedImage",
            file_origin=FileOrigin.CHAT_IMAGE_GEN,
            file_type=get_image_type(base64_string),
        )
        return unique_id


def save_file(
    tenant_id: str,
    url: str | None = None,
    base64_data: str | None = None,
) -> str:
    """Save a file from either a URL or base64 encoded string.

    Args:
        tenant_id: The tenant ID to save the file under
        url: URL to download file from
        base64_data: Base64 encoded file data

    Returns:
        The unique ID of the saved file

    Raises:
        ValueError: If neither url nor base64_data is provided, or if both are provided
    """
    if url is not None and base64_data is not None:
        raise ValueError("Cannot specify both url and base64_data")

    if url is not None:
        return save_file_from_url(url, tenant_id)
    elif base64_data is not None:
        return save_file_from_base64(base64_data, tenant_id)
    else:
        raise ValueError("Must specify either url or base64_data")


def save_files(urls: list[str], base64_files: list[str], tenant_id: str) -> list[str]:
    # NOTE: be explicit about typing so that if we change things, we get notified
    funcs: list[
        tuple[
            Callable[[str, str | None, str | None], str],
            tuple[str, str | None, str | None],
        ]
    ] = [(save_file, (tenant_id, url, None)) for url in urls] + [
        (save_file, (tenant_id, None, base64_file)) for base64_file in base64_files
    ]

    return run_functions_tuples_in_parallel(funcs)
