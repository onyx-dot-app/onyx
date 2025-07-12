import base64
from collections.abc import Callable
from io import BytesIO
from typing import cast
from typing import NamedTuple
from uuid import UUID

import requests
from sqlalchemy.orm import Session

from onyx.configs.constants import FileOrigin
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ChatMessage
from onyx.db.models import UserFile
from onyx.db.models import UserFolder
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.models import ChatFileType
from onyx.file_store.models import FileDescriptor
from onyx.file_store.models import InMemoryChatFile
from onyx.server.query_and_chat.chat_utils import mime_type_to_chat_file_type
from onyx.utils.b64 import get_image_type
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel

logger = setup_logger()


# Using functional syntax to avoid mypy type inference issues with 'index' field
IndexedData = NamedTuple("IndexedData", [("index", int), ("data", str)])
"""Represents data with its original index for maintaining order in parallel processing."""

IndexedResult = NamedTuple("IndexedResult", [("index", int), ("file_id", str)])
"""Represents a processing result with its original index."""


def user_file_id_to_plaintext_file_name(user_file_id: int) -> str:
    """Generate a consistent file name for storing plaintext content of a user file."""
    return f"plaintext_{user_file_id}"


def store_user_file_plaintext(user_file_id: int, plaintext_content: str) -> bool:
    """
    Store plaintext content for a user file in the file store.

    Args:
        user_file_id: The ID of the user file
        plaintext_content: The plaintext content to store

    Returns:
        bool: True if storage was successful, False otherwise
    """
    # Skip empty content
    if not plaintext_content:
        return False

    # Get plaintext file name
    plaintext_file_name = user_file_id_to_plaintext_file_name(user_file_id)

    # Use a separate session to avoid committing the caller's transaction
    try:
        with get_session_with_current_tenant() as file_store_session:
            file_store = get_default_file_store(file_store_session)
            file_content = BytesIO(plaintext_content.encode("utf-8"))
            file_store.save_file(
                content=file_content,
                display_name=f"Plaintext for user file {user_file_id}",
                file_origin=FileOrigin.PLAINTEXT_CACHE,
                file_type="text/plain",
                file_id=plaintext_file_name,
            )
            return True
    except Exception as e:
        logger.warning(f"Failed to store plaintext for user file {user_file_id}: {e}")
        return False


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


def load_user_folder(folder_id: int, db_session: Session) -> list[InMemoryChatFile]:
    user_files = (
        db_session.query(UserFile).filter(UserFile.folder_id == folder_id).all()
    )
    return [load_user_file(file.id, db_session) for file in user_files]


def load_user_file(file_id: int, db_session: Session) -> InMemoryChatFile:
    chat_file_type = ChatFileType.USER_KNOWLEDGE
    status = "not_loaded"

    user_file = db_session.query(UserFile).filter(UserFile.id == file_id).first()
    if not user_file:
        raise ValueError(f"User file with id {file_id} not found")

    # Get the file record to determine the appropriate chat file type
    file_store = get_default_file_store(db_session)
    file_record = file_store.read_file_record(user_file.file_id)

    # Determine appropriate chat file type based on the original file's MIME type
    chat_file_type = mime_type_to_chat_file_type(file_record.file_type)

    # Try to load plaintext version first
    plaintext_file_name = user_file_id_to_plaintext_file_name(file_id)

    # check for plain text normalized version first, then use original file otherwise
    try:
        file_io = file_store.read_file(plaintext_file_name, mode="b")
        # For plaintext versions, use PLAIN_TEXT type (unless it's an image which doesn't have plaintext)
        plaintext_chat_file_type = (
            ChatFileType.PLAIN_TEXT
            if chat_file_type != ChatFileType.IMAGE
            else chat_file_type
        )
        chat_file = InMemoryChatFile(
            file_id=str(user_file.file_id),
            content=file_io.read(),
            file_type=plaintext_chat_file_type,
            filename=user_file.name,
        )
        status = "plaintext"
        return chat_file
    except Exception as e:
        logger.warning(f"Failed to load plaintext for user file {user_file.id}: {e}")
        # Fall back to original file if plaintext not available
        file_io = file_store.read_file(user_file.file_id, mode="b")

        chat_file = InMemoryChatFile(
            file_id=str(user_file.file_id),
            content=file_io.read(),
            file_type=chat_file_type,
            filename=user_file.name,
        )
        status = "original"
        return chat_file
    finally:
        logger.debug(
            f"load_user_file finished: file_id={user_file.file_id} "
            f"chat_file_type={chat_file_type} "
            f"status={status}"
        )


def load_in_memory_chat_files(
    user_file_ids: list[int],
    user_folder_ids: list[int],
    db_session: Session,
) -> list[InMemoryChatFile]:
    """
    Loads the actual content of user files specified by individual IDs and those
    within specified folder IDs into memory.

    Args:
        user_file_ids: A list of specific UserFile IDs to load.
        user_folder_ids: A list of UserFolder IDs. All UserFiles within these folders will be loaded.
        db_session: The SQLAlchemy database session.

    Returns:
        A list of InMemoryChatFile objects, each containing the file content (as bytes),
        file ID, file type, and filename. Prioritizes loading plaintext versions if available.
    """
    # Use parallel execution to load files concurrently
    return cast(
        list[InMemoryChatFile],
        run_functions_tuples_in_parallel(
            # 1. Load files specified by individual IDs
            [(load_user_file, (file_id, db_session)) for file_id in user_file_ids]
        )
        # 2. Load all files within specified folders
        + [
            file
            for folder_id in user_folder_ids
            for file in load_user_folder(folder_id, db_session)
        ],
    )


def get_user_files(
    user_file_ids: list[int],
    user_folder_ids: list[int],
    db_session: Session,
) -> list[UserFile]:
    """
    Fetches UserFile database records based on provided file and folder IDs.

    Args:
        user_file_ids: A list of specific UserFile IDs to fetch.
        user_folder_ids: A list of UserFolder IDs. All UserFiles within these folders will be fetched.
        db_session: The SQLAlchemy database session.

    Returns:
        A list containing UserFile SQLAlchemy model objects corresponding to the
        specified file IDs and all files within the specified folder IDs.
        It does NOT return the actual file content.
    """
    user_files: list[UserFile] = []

    # 1. Fetch UserFile records for specific file IDs
    for user_file_id in user_file_ids:
        # Query the database for a UserFile with the matching ID
        user_file = (
            db_session.query(UserFile).filter(UserFile.id == user_file_id).first()
        )
        # If found, add it to the list
        if user_file is not None:
            user_files.append(user_file)

    # 2. Fetch UserFile records for all files within specified folder IDs
    for user_folder_id in user_folder_ids:
        # Query the database for all UserFiles belonging to the current folder ID
        # and extend the list with the results
        user_files.extend(
            db_session.query(UserFile)
            .filter(UserFile.folder_id == user_folder_id)
            .all()
        )

    # 3. Return the combined list of UserFile database objects
    return user_files


def get_user_files_as_user(
    user_file_ids: list[int],
    user_folder_ids: list[int],
    user_id: UUID | None,
    db_session: Session,
) -> list[UserFile]:
    """
    Fetches all UserFile database records for a given user.
    """
    user_files = get_user_files(user_file_ids, user_folder_ids, db_session)
    for user_file in user_files:
        # Note: if user_id is None, then all files should be None as well
        # (since auth must be disabled in this case)
        if user_file.user_id != user_id:
            raise ValueError(
                f"User {user_id} does not have access to file {user_file.id}"
            )
    return user_files


def save_file_from_url(url: str) -> str:
    """NOTE: using multiple sessions here, since this is often called
    using multithreading. In practice, sharing a session has resulted in
    weird errors."""
    with get_session_with_current_tenant() as db_session:
        response = requests.get(url)
        response.raise_for_status()

        file_io = BytesIO(response.content)
        file_store = get_default_file_store(db_session)
        file_id = file_store.save_file(
            content=file_io,
            display_name="GeneratedImage",
            file_origin=FileOrigin.CHAT_IMAGE_GEN,
            file_type="image/png;base64",
        )
        return file_id


def save_file_from_base64(base64_string: str) -> str:
    with get_session_with_current_tenant() as db_session:
        file_store = get_default_file_store(db_session)
        file_id = file_store.save_file(
            content=BytesIO(base64.b64decode(base64_string)),
            display_name="GeneratedImage",
            file_origin=FileOrigin.CHAT_IMAGE_GEN,
            file_type=get_image_type(base64_string),
        )
        return file_id


def save_file_indexed(
    indexed_url: IndexedData | None = None,
    indexed_base64: IndexedData | None = None,
) -> IndexedResult:
    """Save a file from either indexed URL or base64 data, preserving the original index.

    Args:
        indexed_url: IndexedData with URL
        indexed_base64: IndexedData with base64 data

    Returns:
        IndexedResult with the original index and new file_id

    Raises:
        ValueError: If neither or both parameters are provided
    """
    if indexed_url is not None and indexed_base64 is not None:
        raise ValueError("Cannot specify both indexed_url and indexed_base64")

    if indexed_url is not None:
        file_id = save_file_from_url(indexed_url.data)
        return IndexedResult(index=indexed_url.index, file_id=file_id)
    elif indexed_base64 is not None:
        file_id = save_file_from_base64(indexed_base64.data)
        return IndexedResult(index=indexed_base64.index, file_id=file_id)
    else:
        raise ValueError("Must specify either indexed_url or indexed_base64")


def save_file(
    url: str | None = None,
    base64_data: str | None = None,
) -> str:
    """Save a file from either a URL or base64 encoded string.

    Args:
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
        return save_file_from_url(url)
    elif base64_data is not None:
        return save_file_from_base64(base64_data)
    else:
        raise ValueError("Must specify either url or base64_data")


def save_files(urls: list[str], base64_files: list[str]) -> list[str]:
    # NOTE: be explicit about typing so that if we change things, we get notified
    funcs: list[
        tuple[
            Callable[[str | None, str | None], str],
            tuple[str | None, str | None],
        ]
    ] = [(save_file, (url, None)) for url in urls] + [
        (save_file, (None, base64_file)) for base64_file in base64_files
    ]

    return run_functions_tuples_in_parallel(funcs)


def save_files_indexed(
    indexed_urls: list[IndexedData], indexed_base64_files: list[IndexedData]
) -> list[IndexedResult]:
    """Save multiple files while preserving original indices for proper mapping.

    This function is designed to handle concurrent file saving while maintaining
    the association between input data and output file IDs through explicit indexing.

    Args:
        indexed_urls: List of IndexedData with URLs and their original indices
        indexed_base64_files: List of IndexedData with base64 data and their original indices

    Returns:
        List of IndexedResult containing original indices and corresponding file IDs

    Example:
        urls = [IndexedData(index=0, data="http://example.com/img1.png")]
        base64 = [IndexedData(index=2, data="base64data...")]
        results = save_files_indexed(urls, base64)
        # Results: [IndexedResult(index=0, file_id="file1"), IndexedResult(index=2, file_id="file2")]
    """
    # Combine all tasks with their indices
    funcs: list[
        tuple[
            Callable[[IndexedData | None, IndexedData | None], IndexedResult],
            tuple[IndexedData | None, IndexedData | None],
        ]
    ] = [(save_file_indexed, (indexed_url, None)) for indexed_url in indexed_urls] + [
        (save_file_indexed, (None, indexed_base64))
        for indexed_base64 in indexed_base64_files
    ]

    # Run tasks in parallel and return results with preserved indices
    return run_functions_tuples_in_parallel(funcs)


def load_all_persona_files_for_chat(
    persona_id: int, db_session: Session
) -> tuple[list[InMemoryChatFile], list[int]]:
    from onyx.db.models import Persona
    from sqlalchemy.orm import joinedload

    persona = (
        db_session.query(Persona)
        .filter(Persona.id == persona_id)
        .options(
            joinedload(Persona.user_files),
            joinedload(Persona.user_folders).joinedload(UserFolder.files),
        )
        .one()
    )

    persona_file_calls = [
        (load_user_file, (user_file.id, db_session)) for user_file in persona.user_files
    ]
    persona_loaded_files = run_functions_tuples_in_parallel(persona_file_calls)

    persona_folder_files = []
    persona_folder_file_ids = []
    for user_folder in persona.user_folders:
        folder_files = load_user_folder(user_folder.id, db_session)
        persona_folder_files.extend(folder_files)
        persona_folder_file_ids.extend([file.id for file in user_folder.files])

    persona_files = list(persona_loaded_files) + persona_folder_files
    persona_file_ids = [
        file.id for file in persona.user_files
    ] + persona_folder_file_ids

    return persona_files, persona_file_ids
