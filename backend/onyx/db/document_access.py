"""SQL filters matching indexed document visibility."""

from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Select, String, and_, any_, cast, false, or_, select, tuple_
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.elements import ColumnElement

from onyx.configs.constants import DocumentSource
from onyx.db.connector_credential_pair import (
    build_restricted_acl_guard,
    build_user_cc_pair_access_filter,
    has_guarded_cc_pairs,
)
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus
from onyx.db.models import (
    Connector,
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

    # Source ACL columns only count on a perm-synced pair's row.
    acl_match = and_(
        ConnectorCredentialPair.access_type.in_(AccessType.perm_synced_types()),
        _document_acl_match(
            db_session, user_email, external_group_ids, user_id, prior_emails
        ),
    )
    return stmt.where(or_(_open_cc_pair_clause(user_id), acl_match))


class DocumentAccessPairs(BaseModel):
    """`apply_document_access_filter`'s pair-level checks, resolved to
    (connector_id, credential_id) pairs before the document query."""

    # Pairs whose documents the user sees with no document ACL match.
    open_pairs: list[tuple[int, int]]
    # Perm-synced pairs whose documents need a document ACL match.
    acl_pairs: list[tuple[int, int]]


def resolve_document_access_pairs(
    db_session: Session,
    user_id: UUID | None,
    source_types: list[DocumentSource] | None = None,
) -> DocumentAccessPairs:
    """The pairs that can grant the user documents, optionally of the given
    sources. A document query that joins the pair table lets the planner guess
    each pair's size from the two key columns alone, and a large connector
    then gets a plan that visits every one of its documents."""
    is_open = _open_cc_pair_clause(user_id)
    is_acl = ConnectorCredentialPair.access_type.in_(AccessType.perm_synced_types())
    stmt = select(
        ConnectorCredentialPair.connector_id,
        ConnectorCredentialPair.credential_id,
        is_open,
    ).where(
        ConnectorCredentialPair.status != ConnectorCredentialPairStatus.DELETING,
        or_(is_open, is_acl),
    )
    if source_types is not None:
        stmt = stmt.join(
            Connector, Connector.id == ConnectorCredentialPair.connector_id
        ).where(Connector.source.in_(source_types))
    pairs = DocumentAccessPairs(open_pairs=[], acl_pairs=[])
    for connector_id, credential_id, open_pair in db_session.execute(stmt).tuples():
        target = pairs.open_pairs if open_pair else pairs.acl_pairs
        target.append((connector_id, credential_id))
    return pairs


def apply_resolved_document_access_filter(
    db_session: Session,
    stmt: Select,
    pairs: DocumentAccessPairs,
    user_email: str | None,
    external_group_ids: list[str],
    user_id: UUID | None = None,
    prior_emails: list[str] | None = None,
) -> Select:
    """`apply_document_access_filter` with its pair checks already resolved.
    Joins `DocumentByConnectorCredentialPair` but not the pair table, so a
    document in several granting pairs still yields one row per pair."""
    stmt = stmt.join(
        DocumentByConnectorCredentialPair,
        Document.id == DocumentByConnectorCredentialPair.id,
    )
    row_pair = tuple_(
        DocumentByConnectorCredentialPair.connector_id,
        DocumentByConnectorCredentialPair.credential_id,
    )
    access_filters: list[ColumnElement[bool]] = []
    if pairs.open_pairs:
        access_filters.append(row_pair.in_(pairs.open_pairs))
    if pairs.acl_pairs:
        access_filters.append(
            and_(
                row_pair.in_(pairs.acl_pairs),
                _document_acl_match(
                    db_session, user_email, external_group_ids, user_id, prior_emails
                ),
            )
        )
    return stmt.where(or_(*access_filters) if access_filters else false())


def _open_cc_pair_clause(user_id: UUID | None) -> ColumnElement[bool]:
    """Pairs whose documents the user may see with no document ACL match."""
    if user_id:
        # Includes PUBLIC pairs.
        return build_user_cc_pair_access_filter(user_id)
    return ConnectorCredentialPair.access_type == AccessType.PUBLIC


def _document_acl_match(
    db_session: Session,
    user_email: str | None,
    external_group_ids: list[str],
    user_id: UUID | None,
    prior_emails: list[str] | None,
) -> ColumnElement[bool]:
    """The document's own ACL grants the user access."""
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
    # The guard's per-row EXISTS checks can only matter once a guarded pair exists.
    if has_guarded_cc_pairs(db_session):
        acl_match = and_(
            acl_match, build_restricted_acl_guard(user_id, _document_has_cc_pair)
        )
    return acl_match


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
    prior_emails: list[str] | None = None,
) -> list[Document]:
    """Return requested documents allowed by the retrieval-time access policy.
    `prior_emails`: the user's earlier emails, which synced ACLs can still
    name, as search matches them."""
    if not document_ids:
        return []

    stmt = select(Document).where(Document.id.in_(document_ids))
    stmt = apply_document_access_filter(
        db_session,
        stmt,
        user_email,
        external_group_ids,
        user_id=user_id,
        prior_emails=prior_emails,
    )
    stmt = stmt.distinct()
    return list(db_session.execute(stmt).scalars().all())
