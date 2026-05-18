"""Push user-uploaded files to running sandboxes."""

from uuid import UUID

from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.document import get_documents_by_source
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.db.sandbox import get_sandbox_user_map
from onyx.server.features.build.sandbox.base import get_sandbox_manager
from onyx.server.features.build.sandbox.models import FileSet
from onyx.server.features.build.sandbox.models import PushResult
from onyx.utils.logger import setup_logger

logger = setup_logger()

USER_FILES_MOUNT_PATH = "/workspace/managed/user_files"


def build_user_files_fileset(user_id: UUID, db_session: Session) -> FileSet:
    """Return a flat ``{path: bytes}`` map of every user file eligible for sync."""
    docs = get_documents_by_source(
        db_session,
        source=DocumentSource.CRAFT_FILE,
        creator_id=user_id,
    )

    files: FileSet = {}
    file_store = get_default_file_store()

    for doc in docs:
        meta = doc.doc_metadata or {}
        if meta.get("is_directory"):
            continue
        if meta.get("sync_disabled"):
            continue

        file_path = meta.get("file_path")
        if not file_path:
            continue
        file_path = file_path.lstrip("/")

        if not doc.link:
            continue

        try:
            blob = file_store.read_file(doc.link)
            files[file_path] = blob.read()
        except Exception:
            logger.warning(
                "Failed to read user file %s (%s), skipping",
                file_path,
                doc.link,
            )

    return files


def hydrate_user_files(
    sandbox_id: UUID,
    user_id: UUID,
    db_session: Session,
) -> PushResult:
    """Push all user files to a single sandbox (cold-start hydration)."""
    files = build_user_files_fileset(user_id, db_session)
    return get_sandbox_manager().push_to_sandbox(
        sandbox_id=sandbox_id,
        mount_path=USER_FILES_MOUNT_PATH,
        files=files,
    )


def sync_user_files_to_active_sandboxes(
    user_id: UUID,
    db_session: Session,
) -> None:
    """Rebuild and push user files to every active sandbox for the user."""
    try:
        sandbox_map = get_sandbox_user_map([user_id], db_session)
        if not sandbox_map:
            return

        files = build_user_files_fileset(user_id, db_session)
        sandbox_files = {sandbox_id: files for sandbox_id in sandbox_map}
        result = get_sandbox_manager().push_to_sandboxes(
            mount_path=USER_FILES_MOUNT_PATH,
            sandbox_files=sandbox_files,
        )
        for failure in result.failures:
            logger.warning(
                "User file push failed for sandbox %s: %s: %s",
                failure.sandbox_id,
                failure.reason,
                failure.detail,
            )
    except Exception:
        logger.exception("Failed to push user files to sandboxes")
