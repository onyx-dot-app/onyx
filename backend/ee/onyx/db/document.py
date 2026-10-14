from datetime import datetime, timezone

from sqlalchemy import and_, exists, select
from sqlalchemy.orm import Session

from onyx.access.models import ExternalAccess
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.db.enums import AccessType
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    DocumentByConnectorCredentialPair,
)
from onyx.db.models import Document as DbDocument


def _has_indexed_permission_synced_onedrive_relationship(
    db_session: Session,
    doc_id: str,
) -> bool:
    stmt = select(
        exists().where(
            DocumentByConnectorCredentialPair.id == doc_id,
            DocumentByConnectorCredentialPair.has_been_indexed.is_(True),
            Connector.id == DocumentByConnectorCredentialPair.connector_id,
            Connector.source == DocumentSource.ONEDRIVE,
            and_(
                ConnectorCredentialPair.connector_id
                == DocumentByConnectorCredentialPair.connector_id,
                ConnectorCredentialPair.credential_id
                == DocumentByConnectorCredentialPair.credential_id,
            ),
            ConnectorCredentialPair.access_type.in_(AccessType.perm_synced_types()),
        )
    )
    return bool(db_session.scalar(stmt))


def upsert_document_external_perms(
    db_session: Session,
    doc_id: str,
    external_access: ExternalAccess,
    source_type: DocumentSource,
) -> bool:
    """
    This sets the permissions for a document in postgres. Returns True if the
    a new document was created, False otherwise.
    NOTE: this will replace any existing external access, it will not do a union
    """
    document = db_session.scalar(
        select(DbDocument).where(DbDocument.id == doc_id).with_for_update()
    )

    prefixed_external_groups: set[str] = {
        build_ext_group_name_for_onyx(
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
        return True

    if (
        source_type == DocumentSource.SHAREPOINT
        and _has_indexed_permission_synced_onedrive_relationship(
            db_session,
            doc_id,
        )
    ):
        return False

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

    return False
