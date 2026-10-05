"""SQL filters matching indexed document visibility."""

from uuid import UUID

from sqlalchemy import Select, String, and_, any_, cast, or_, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.elements import ColumnElement

from onyx.db.connector_credential_pair import (
    build_restricted_acl_guard,
    build_user_cc_pair_access_filter,
    has_sync_restricted_cc_pairs,
)
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus
from onyx.db.models import (
    ConnectorCredentialPair,
    Document,
    DocumentByConnectorCredentialPair,
)


def apply_document_access_filter(
    db_session: Session,
    stmt: Select,
    user_email: str | None,
    external_group_ids: list[str],
    user_id: UUID | None = None,
    prior_emails: list[str] | None = None,
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

    acl_filters: list[ColumnElement[bool]] = [Document.is_public.is_(True)]
    if user_email:
        acl_filters.append(any_(Document.external_user_emails) == user_email)
    if prior_emails:
        acl_filters.append(
            Document.external_user_emails.overlap(
                cast(postgresql.array(prior_emails), postgresql.ARRAY(String))
            )
        )
    if external_group_ids:
        acl_filters.append(
            Document.external_user_group_ids.overlap(
                cast(postgresql.array(external_group_ids), postgresql.ARRAY(String))
            )
        )
    acl_match = or_(*acl_filters)
    # The guard's per-row EXISTS checks can only matter once a restricted pair exists.
    if has_sync_restricted_cc_pairs(db_session):
        acl_match = and_(
            acl_match, build_restricted_acl_guard(user_id, _document_has_cc_pair)
        )
    access_filters: list[ColumnElement[bool]] = [
        ConnectorCredentialPair.access_type == AccessType.PUBLIC,
        acl_match,
    ]
    if user_id:
        access_filters.append(build_user_cc_pair_access_filter(user_id))

    return stmt.where(or_(*access_filters))


def _document_has_cc_pair(clause: ColumnElement[bool]) -> ColumnElement[bool]:
    doc_cc_pair = aliased(DocumentByConnectorCredentialPair)
    return (
        select(1)
        .select_from(doc_cc_pair)
        .join(
            ConnectorCredentialPair,
            and_(
                doc_cc_pair.connector_id == ConnectorCredentialPair.connector_id,
                doc_cc_pair.credential_id == ConnectorCredentialPair.credential_id,
            ),
        )
        .where(doc_cc_pair.id == Document.id, clause)
        .correlate(Document)
        .exists()
    )


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
        db_session, stmt, user_email, external_group_ids, user_id=user_id
    )
    stmt = stmt.distinct()
    return list(db_session.execute(stmt).scalars().all())
