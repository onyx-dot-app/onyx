"""
Document access filtering utilities.

This module provides reusable access filtering logic for documents based on:
- Connector access type (PUBLIC vs SYNC)
- Document-level public flag
- User email matching external_user_emails
- User group overlap with external_user_group_ids

This is a standalone module to avoid circular imports between document.py and persona.py.
"""

from sqlalchemy import and_
from sqlalchemy import any_
from sqlalchemy import or_
from sqlalchemy import Select
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Document
from onyx.db.models import DocumentByConnectorCredentialPair


def apply_document_access_filter(
    stmt: Select,
    user_email: str | None,
    external_group_ids: list[str],
) -> Select:
    """
    Apply document access filtering to a query.

    This joins with DocumentByConnectorCredentialPair and ConnectorCredentialPair to:
    1. Check if the document is from a PUBLIC connector (access_type = PUBLIC)
    2. Check document-level permissions (is_public, external_user_emails, external_user_group_ids)
    3. Exclude documents from cc_pairs that are being deleted

    Args:
        stmt: The SELECT statement to modify (must be selecting from Document)
        user_email: The user's email for permission checking
        external_group_ids: List of external group IDs the user belongs to

    Returns:
        Modified SELECT statement with access filtering applied
    """
    # Join to get cc_pair info for each document
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

    # Exclude documents from cc_pairs that are being deleted
    stmt = stmt.where(
        ConnectorCredentialPair.status != ConnectorCredentialPairStatus.DELETING
    )

    # Build access filters
    access_filters: list[ColumnElement[bool]] = [
        # Document is from a PUBLIC connector
        ConnectorCredentialPair.access_type == AccessType.PUBLIC,
        # Document is marked as public (e.g., "Anyone with link" in source)
        Document.is_public.is_(True),
    ]
    if user_email:
        access_filters.append(any_(Document.external_user_emails) == user_email)
    if external_group_ids:
        access_filters.append(
            Document.external_user_group_ids.overlap(
                postgresql.array(external_group_ids)
            )
        )

    stmt = stmt.where(or_(*access_filters))
    return stmt


def get_accessible_documents_by_ids(
    db_session: Session,
    document_ids: list[str],
    user_email: str | None,
    external_group_ids: list[str],
) -> list[Document]:
    """
    Fetch documents by IDs, filtering to only those the user has access to.

    Uses the same access filtering logic as other document queries:
    - Documents from PUBLIC connectors
    - Documents marked as public (e.g., "Anyone with link")
    - Documents where user email matches external_user_emails
    - Documents where user's groups overlap with external_user_group_ids

    Args:
        db_session: Database session
        document_ids: List of document IDs to fetch
        user_email: User's email for permission checking
        external_group_ids: List of external group IDs the user belongs to

    Returns:
        List of Document objects from the input that the user has access to
    """
    if not document_ids:
        return []

    stmt = select(Document).where(Document.id.in_(document_ids))
    stmt = apply_document_access_filter(stmt, user_email, external_group_ids)
    # Use distinct to avoid duplicates when a document belongs to multiple cc_pairs
    stmt = stmt.distinct()
    return list(db_session.execute(stmt).scalars().all())
