import datetime
from uuid import UUID

from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from onyx.configs.constants import FileOrigin
from onyx.db.models import ChatMessage
from onyx.db.models import ChatSession
from onyx.db.models import ChatSessionSharedStatus
from onyx.db.models import FileRecord
from onyx.db.models import Persona
from onyx.db.models import Project__UserFile
from onyx.db.models import UserFile


def fetch_chunk_counts_for_user_files(
    user_file_ids: list[str],
    db_session: Session,
) -> list[tuple[str, int]]:
    """
    Return a list of (user_file_id, chunk_count) tuples.
    If a user_file_id is not found in the database, it will be returned with a chunk_count of 0.
    """
    stmt = select(UserFile.id, UserFile.chunk_count).where(
        UserFile.id.in_(user_file_ids)
    )

    results = db_session.execute(stmt).all()

    # Create a dictionary of user_file_id to chunk_count
    chunk_counts = {str(row.id): row.chunk_count or 0 for row in results}

    # Return a list of tuples, preserving `None` for documents not found or with
    # an unknown chunk count. Callers should handle the `None` case and fall
    # back to an existence check against the vector DB if necessary.
    return [
        (user_file_id, chunk_counts.get(user_file_id, 0))
        for user_file_id in user_file_ids
    ]


def calculate_user_files_token_count(file_ids: list[UUID], db_session: Session) -> int:
    """Calculate total token count for specified files"""
    total_tokens = 0

    # Get tokens from individual files
    if file_ids:
        file_tokens = (
            db_session.query(func.sum(UserFile.token_count))
            .filter(UserFile.id.in_(file_ids))
            .scalar()
            or 0
        )
        total_tokens += file_tokens

    return total_tokens


def fetch_user_project_ids_for_user_files(
    user_file_ids: list[str],
    db_session: Session,
) -> dict[str, list[int]]:
    """Fetch user project ids for specified user files"""
    user_file_uuid_ids = [UUID(user_file_id) for user_file_id in user_file_ids]
    stmt = select(Project__UserFile.user_file_id, Project__UserFile.project_id).where(
        Project__UserFile.user_file_id.in_(user_file_uuid_ids)
    )
    rows = db_session.execute(stmt).all()

    user_file_id_to_project_ids: dict[str, list[int]] = {
        user_file_id: [] for user_file_id in user_file_ids
    }
    for user_file_id, project_id in rows:
        user_file_id_to_project_ids[str(user_file_id)].append(project_id)

    return user_file_id_to_project_ids


def fetch_persona_ids_for_user_files(
    user_file_ids: list[str],
    db_session: Session,
) -> dict[str, list[int]]:
    """Fetch persona (assistant) ids for specified user files."""
    stmt = (
        select(UserFile)
        .where(UserFile.id.in_(user_file_ids))
        .options(selectinload(UserFile.assistants))
    )
    results = db_session.execute(stmt).scalars().all()
    return {
        str(user_file.id): [persona.id for persona in user_file.assistants]
        for user_file in results
    }


def update_last_accessed_at_for_user_files(
    user_file_ids: list[UUID],
    db_session: Session,
) -> None:
    """Update `last_accessed_at` to now (UTC) for the given user files."""
    if not user_file_ids:
        return
    now = datetime.datetime.now(datetime.timezone.utc)
    (
        db_session.query(UserFile)
        .filter(UserFile.id.in_(user_file_ids))
        .update({UserFile.last_accessed_at: now}, synchronize_session=False)
    )
    db_session.commit()


def get_file_id_by_user_file_id(
    user_file_id: str, user_id: UUID, db_session: Session
) -> str | None:
    user_file = (
        db_session.query(UserFile)
        .filter(UserFile.id == user_file_id, UserFile.user_id == user_id)
        .first()
    )
    if user_file:
        return user_file.file_id
    return None


def user_can_access_chat_file(file_id: str, user_id: UUID, db_session: Session) -> bool:
    """Return True if `user_id` is allowed to read the raw `file_id` served by
    `GET /chat/file/{file_id}`. Access is granted when any of:

    - The `file_id` is the storage id of a `UserFile` owned by the user.
    - The `file_id` is a persona avatar (`Persona.uploaded_image_id`); avatars
      are visible to any authenticated user.
    - The `file_id` appears in a `ChatMessage.files` descriptor of a chat
      session the user owns or a session publicly shared via
      `ChatSessionSharedStatus.PUBLIC`.
    """
    owns_user_file = db_session.query(
        select(UserFile.id)
        .where(UserFile.file_id == file_id, UserFile.user_id == user_id)
        .exists()
    ).scalar()
    if owns_user_file:
        return True

    # TODO: move persona avatars to a dedicated endpoint (e.g.
    # /assistants/{id}/avatar) so this branch can be removed. /chat/file is
    # currently overloaded with multiple asset classes (user files, chat
    # attachments, tool outputs, avatars), forcing this access-check fan-out.
    #
    # Restrict the avatar path to CHAT_UPLOAD-origin files so an attacker
    # cannot bind another user's USER_FILE (or any other origin) to their
    # own persona and read it through this check.
    is_persona_avatar = db_session.query(
        select(Persona.id)
        .join(FileRecord, FileRecord.file_id == Persona.uploaded_image_id)
        .where(
            Persona.uploaded_image_id == file_id,
            FileRecord.file_origin == FileOrigin.CHAT_UPLOAD,
        )
        .exists()
    ).scalar()
    if is_persona_avatar:
        return True

    chat_file_stmt = (
        select(ChatMessage.id)
        .join(ChatSession, ChatMessage.chat_session_id == ChatSession.id)
        .where(ChatMessage.files.op("@>")([{"id": file_id}]))
        .where(
            or_(
                ChatSession.user_id == user_id,
                ChatSession.shared_status == ChatSessionSharedStatus.PUBLIC,
            )
        )
        .limit(1)
    )
    return db_session.execute(chat_file_stmt).first() is not None


def get_file_ids_by_user_file_ids(
    user_file_ids: list[UUID], db_session: Session
) -> list[str]:
    user_files = db_session.query(UserFile).filter(UserFile.id.in_(user_file_ids)).all()
    return [user_file.file_id for user_file in user_files]


def fetch_user_files_with_access_relationships(
    user_file_ids: list[str],
    db_session: Session,
    eager_load_groups: bool = False,
) -> list[UserFile]:
    """Fetch user files with the owner and assistant relationships
    eagerly loaded (needed for computing access control).

    When eager_load_groups is True, Persona.groups is also loaded so that
    callers can extract user-group names without a second DB round-trip."""
    persona_sub_options = [
        selectinload(Persona.users),
        selectinload(Persona.user),
    ]
    if eager_load_groups:
        persona_sub_options.append(selectinload(Persona.groups))

    return (
        db_session.query(UserFile)
        .options(
            joinedload(UserFile.user),
            selectinload(UserFile.assistants).options(*persona_sub_options),
        )
        .filter(UserFile.id.in_(user_file_ids))
        .all()
    )
