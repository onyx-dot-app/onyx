from datetime import datetime
from datetime import timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.access.models import ExternalAccess
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.db.models import Document as DbDocument
from onyx.utils.logger import setup_logger

logger = setup_logger()


def upsert_document_external_perms(
    db_session: Session,
    doc_id: str,
    external_access: ExternalAccess,
    source_type: DocumentSource,
) -> None:
    """
    This sets the permissions for an existing document in postgres. If the
    document has not been indexed yet, this is a no-op.
    NOTE: this will replace any existing external access, it will not do a union
    """
    document = db_session.scalars(
        select(DbDocument).where(DbDocument.id == doc_id)
    ).first()

    if not document:
        # Do NOT pre-create a skeleton row here. The old behavior inserted
        # DbDocument(id=doc_id, semantic_id="") to "stage" permissions for a
        # doc that indexing would later populate. That row has no chunk_count,
        # which is an invalid state for the OpenSearch backend and floods
        # document_index_metadata_sync_task with ChunkCountNotFoundError. The
        # indexing pipeline's upsert is already permission-aware (it populates
        # the external access fields from Document.external_access on insert),
        # so permissions land the moment the doc itself does. Worst case, the
        # doc is picked up by the next permission sync run after indexing.
        # debug level since this can fire for every not-yet-indexed doc a
        # perm sync run enumerates, which can be a very large number
        logger.debug(
            f"Skipping permission upsert for doc_id={doc_id} since it has not "
            "been indexed yet. Permissions will be set when the document is "
            "indexed or on the next permission sync run."
        )
        return

    prefixed_external_groups: set[str] = {
        build_ext_group_name_for_onyx(
            ext_group_name=group_id,
            source=source_type,
        )
        for group_id in external_access.external_user_group_ids
    }

    # If the document exists, we need to check if the external access has changed
    if (
        external_access.external_user_emails != set(document.external_user_emails or [])
        or prefixed_external_groups != set(document.external_user_group_ids or [])
        or external_access.is_public != document.is_public
    ):
        document.external_user_emails = list(external_access.external_user_emails)
        document.external_user_group_ids = list(prefixed_external_groups)
        document.is_public = external_access.is_public
        document.last_modified = datetime.now(timezone.utc)
        db_session.commit()
