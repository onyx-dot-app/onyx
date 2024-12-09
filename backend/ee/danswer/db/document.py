from datetime import datetime
from datetime import timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from danswer.access.models import ExternalAccess
from danswer.access.utils import prefix_group_w_source
from danswer.configs.constants import DocumentSource
from danswer.db.models import Document as DbDocument


def upsert_document_external_perms__no_commit(
    db_session: Session,
    doc_id: str,
    external_access: ExternalAccess,
    source_type: DocumentSource,
) -> None:
    """
    This sets the permissions for a document in postgres.
    NOTE: this will replace any existing external access, it will not do a union
    """
    document = db_session.scalars(
        select(DbDocument).where(DbDocument.id == doc_id)
    ).first()

    prefixed_external_groups = [
        prefix_group_w_source(
            ext_group_name=group_id,
            source=source_type,
        )
        for group_id in external_access.external_user_group_ids
    ]

    if not document:
        # If the document does not exist, still store the external access
        # So that if the document is added later, the external access is already stored
        document = DbDocument(
            id=doc_id,
            semantic_id="",
            external_user_emails=external_access.external_user_emails,
            external_user_group_ids=prefixed_external_groups,
            is_public=external_access.is_public,
        )
        db_session.add(document)
        return

    document.external_user_emails = list(external_access.external_user_emails)
    document.external_user_group_ids = prefixed_external_groups
    document.is_public = external_access.is_public


def upsert_document_external_perms(
    db_session: Session,
    doc_id: str,
    external_access: ExternalAccess,
    source_type: DocumentSource,
) -> None:
    """
    This sets the permissions for a document in postgres.
    NOTE: this will replace any existing external access, it will not do a union
    """
    document = db_session.scalars(
        select(DbDocument).where(DbDocument.id == doc_id)
    ).first()

    prefixed_external_groups: set[str] = {
        prefix_group_w_source(
            ext_group_name=group_id,
            source=source_type,
        )
        for group_id in external_access.external_user_group_ids
    }

    if not document:
        # If the document does not exist, still store the external access
        # So that if the document is added later, the external access is already stored
        # The upsert function in the indexing pipeline does not overwrite the permissions fields
        document = DbDocument(
            id=doc_id,
            semantic_id="",
            external_user_emails=external_access.external_user_emails,
            external_user_group_ids=prefixed_external_groups,
            is_public=external_access.is_public,
        )
        db_session.add(document)
        db_session.commit()
        return

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
