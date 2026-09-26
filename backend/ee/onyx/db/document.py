from sqlalchemy.orm import Session

from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.db.document import (
    get_document_ids_with_other_acl_contributors,
    upsert_document_acl_contributions__no_commit,
)


def upsert_document_external_perms(
    db_session: Session,
    doc_id: str,
    connector_id: int,
    credential_id: int,
    external_access: ExternalAccess,
    source_type: DocumentSource,
    multi_source_document_ids: set[str] | None = None,
) -> None:
    if multi_source_document_ids is None:
        multi_source_document_ids = get_document_ids_with_other_acl_contributors(
            db_session,
            [doc_id],
            connector_id,
            credential_id,
        )
    upsert_document_acl_contributions__no_commit(
        db_session=db_session,
        connector_id=connector_id,
        credential_id=credential_id,
        document_ids=[doc_id],
        external_access_by_document_id={doc_id: external_access},
        source=source_type,
        multi_source_document_ids=multi_source_document_ids,
    )
    db_session.commit()
