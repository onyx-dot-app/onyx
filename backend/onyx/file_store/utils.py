import base64
from collections.abc import Callable
from io import BytesIO
from typing import cast
from uuid import UUID

import requests
from sqlalchemy.orm import Session

from onyx.configs.app_configs import WEB_DOMAIN
from onyx.configs.constants import FileOrigin
from onyx.db.models import UserFile
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.models import ChatFileType
from onyx.file_store.models import FileDescriptor
from onyx.file_store.models import InMemoryChatFile
from onyx.server.query_and_chat.chat_utils import mime_type_to_chat_file_type
from onyx.utils.b64 import get_image_type
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel
from onyx.utils.timing import log_function_time

logger = setup_logger()


def user_file_id_to_plaintext_file_name(user_file_id: UUID) -> str:
    """Generate a consistent file name for storing plaintext content of a user file."""
    return f"plaintext_{user_file_id}"


def store_user_file_plaintext(user_file_id: UUID, plaintext_content: str) -> bool:
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

    try:
        file_store = get_default_file_store()
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


def load_user_file(file_id: UUID, db_session: Session) -> InMemoryChatFile:
    status = "not_loaded"

    user_file = db_session.query(UserFile).filter(UserFile.id == file_id).first()
    if not user_file:
        raise ValueError(f"User file with id {file_id} not found")

    # Get the file record to determine the appropriate chat file type
    file_store = get_default_file_store()
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

        # if we have plaintext for image (which happens when image extraction is enabled), we use PLAIN_TEXT type
        if file_io is not None:
            plaintext_chat_file_type = ChatFileType.PLAIN_TEXT

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
    user_file_ids: list[UUID],
    db_session: Session,
) -> list[InMemoryChatFile]:
    """
    Loads the actual content of user files specified by individual IDs and those
    within specified project IDs into memory.

    Args:
        user_file_ids: A list of specific UserFile IDs to load.
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
        ),
    )


def get_user_files(
    user_file_ids: list[UUID],
    db_session: Session,
) -> list[UserFile]:
    """
    Fetches UserFile database records based on provided file and project IDs.

    Args:
        user_file_ids: A list of specific UserFile IDs to fetch.
        db_session: The SQLAlchemy database session.

    Returns:
        A list containing UserFile SQLAlchemy model objects corresponding to the
        specified file IDs and all files within the specified project IDs.
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

    # 3. Return the combined list of UserFile database objects
    return user_files


def validate_user_files_ownership(
    user_file_ids: list[UUID],
    user_id: UUID | None,
    db_session: Session,
) -> list[UserFile]:
    """
    Fetches all UserFile database records for a given user.
    """
    user_files = get_user_files(user_file_ids, db_session)
    current_user_files = []
    for user_file in user_files:
        # Note: if user_id is None, then all files should be None as well
        # (since auth must be disabled in this case)
        if user_file.user_id != user_id:
            raise ValueError(
                f"User {user_id} does not have access to file {user_file.id}"
            )
        current_user_files.append(user_file)

    return current_user_files


def save_file_from_url(url: str) -> str:
    response = requests.get(url)
    response.raise_for_status()

    file_io = BytesIO(response.content)
    file_store = get_default_file_store()
    file_id = file_store.save_file(
        content=file_io,
        display_name="GeneratedImage",
        file_origin=FileOrigin.CHAT_IMAGE_GEN,
        file_type="image/png;base64",
    )
    return file_id


def save_file_from_base64(base64_string: str) -> str:
    file_store = get_default_file_store()
    file_id = file_store.save_file(
        content=BytesIO(base64.b64decode(base64_string)),
        display_name="GeneratedImage",
        file_origin=FileOrigin.CHAT_IMAGE_GEN,
        file_type=get_image_type(base64_string),
    )
    return file_id


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


@log_function_time(print_only=True)
def verify_user_files(
    user_files: list[FileDescriptor],
    user_id: UUID | None,
    db_session: Session,
    project_id: int | None = None,
) -> None:
    """
    Verify that all provided file descriptors belong to the specified user.
    For project files (those without user_file_id), verifies access through project ownership.

    Args:
        user_files: List of file descriptors to verify
        user_id: The user ID to check ownership against
        db_session: The SQLAlchemy database session
        project_id: Optional project ID to verify project file access against

    Raises:
        ValueError: If any file does not belong to the user or is not found
    """
    from onyx.db.models import Project__UserFile
    from onyx.db.projects import check_project_ownership

    # Extract user_file_ids and project file_ids from the file descriptors
    user_file_ids = []
    project_file_ids = []

    for file_descriptor in user_files:
        # Check if this file descriptor has a user_file_id
        if "user_file_id" in file_descriptor and file_descriptor["user_file_id"]:
            try:
                user_file_ids.append(UUID(file_descriptor["user_file_id"]))
            except (ValueError, TypeError):
                logger.warning(
                    f"Invalid user_file_id in file descriptor: {file_descriptor.get('user_file_id')}"
                )
                continue
        else:
            # This is a project file - use the 'id' field which is the file_id
            if "id" in file_descriptor and file_descriptor["id"]:
                project_file_ids.append(file_descriptor["id"])

    # Verify user files (existing logic)
    if user_file_ids:
        validate_user_files_ownership(user_file_ids, user_id, db_session)

    # Verify project files
    if project_file_ids:
        if project_id is None:
            raise ValueError(
                "Project files provided but no project_id specified for verification"
            )

        # Verify user owns the project
        if not check_project_ownership(project_id, user_id, db_session):
            raise ValueError(
                f"User {user_id} does not have access to project {project_id}"
            )

        # Verify all project files belong to the specified project
        user_files_in_project = (
            db_session.query(UserFile)
            .join(Project__UserFile)
            .filter(
                Project__UserFile.project_id == project_id,
                UserFile.file_id.in_(project_file_ids),
            )
            .all()
        )

        # Check if all files were found in the project
        found_file_ids = {uf.file_id for uf in user_files_in_project}
        missing_files = set(project_file_ids) - found_file_ids

        if missing_files:
            raise ValueError(
                f"Files {missing_files} are not associated with project {project_id}"
            )


def build_frontend_file_url(file_id: str) -> str:
    return f"/api/chat/file/{file_id}"


def build_full_frontend_file_url(file_id: str) -> str:
    return f"{WEB_DOMAIN}/api/chat/file/{file_id}"
