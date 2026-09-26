from sqlalchemy.orm import Session

from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.db.document import upsert_document_acl_contributions__no_commit


def upsert_document_external_perms(
    db_session: Session,
    doc_id: str,
    connector_id: int,
    credential_id: int,
    external_access: ExternalAccess,
    source_type: DocumentSource,
) -> None:
    upsert_document_acl_contributions__no_commit(
        db_session=db_session,
        connector_id=connector_id,
        credential_id=credential_id,
        document_ids=[doc_id],
        external_access_by_document_id={doc_id: external_access},
        source=source_type,
    )
    db_session.commit()
