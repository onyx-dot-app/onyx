"""SQL filters matching indexed document visibility."""

from uuid import UUID

from sqlalchemy import Select, String, and_, any_, cast, or_, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from onyx.db.connector_credential_pair import build_user_cc_pair_access_filter
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus
from onyx.db.models import (
    ConnectorCredentialPair,
    Document,
    DocumentByConnectorCredentialPair,
)


def apply_document_access_filter(
    stmt: Select,
    user_email: str | None,
    external_group_ids: list[str],
    user_id: UUID | None = None,
) -> Select:
    """Filter documents by source ACL or associated connector access."""
    stmt = stmt.join(
        DocumentByConnectorCredentialPair,
        Document.id == DocumentByConnectorCredentialPair.id,
    ).join(
        ConnectorCredentialPair,
        and_(
            DocumentByConnectorCredentialPair.connector_id
            == ConnectorCredentialPair.connector_id,
            DocumentByConnectorCredentialPair.credential_id
            == ConnectorCredentialPair.credential_id,
        ),
    )

    stmt = stmt.where(
        ConnectorCredentialPair.status != ConnectorCredentialPairStatus.DELETING
    )

    access_filters: list[ColumnElement[bool]] = [
        ConnectorCredentialPair.access_type == AccessType.PUBLIC,
        Document.is_public.is_(True),
    ]
    if user_email:
        access_filters.append(any_(Document.external_user_emails) == user_email)
    if external_group_ids:
        access_filters.append(
            Document.external_user_group_ids.overlap(
                cast(postgresql.array(external_group_ids), postgresql.ARRAY(String))
            )
        )
    if user_id:
        access_filters.append(build_user_cc_pair_access_filter(user_id))

    return stmt.where(or_(*access_filters))


def get_accessible_documents_by_ids(
    db_session: Session,
    document_ids: list[str],
    user_email: str | None,
    external_group_ids: list[str],
    user_id: UUID | None = None,
) -> list[Document]:
    """Return requested documents allowed by the retrieval-time access policy."""
    if not document_ids:
        return []

    stmt = select(Document).where(Document.id.in_(document_ids))
    stmt = apply_document_access_filter(
        stmt, user_email, external_group_ids, user_id=user_id
    )
    stmt = stmt.distinct()
    return list(db_session.execute(stmt).scalars().all())
