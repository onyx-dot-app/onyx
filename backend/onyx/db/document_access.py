"""
Document access filtering utilities.

This module provides reusable access filtering logic for documents based on:
- Public connectors and private connector ownership/group membership
- Document-level public flag
- User email matching external_user_emails
- User group overlap with external_user_group_ids

This is a standalone module to avoid circular imports between document.py and persona.py.
"""

from sqlalchemy import and_
from sqlalchemy import any_
from sqlalchemy import cast
from sqlalchemy import exists
from sqlalchemy import or_
from sqlalchemy import Select
from sqlalchemy import select
from sqlalchemy import String
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Credential
from onyx.db.models import Document
from onyx.db.models import DocumentByConnectorCredentialPair
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.db.models import UserGroup__ConnectorCredentialPair


def apply_document_access_filter(
    stmt: Select,
    user_email: str | None,
    external_group_ids: list[str],
) -> Select:
    """
    Apply document access filtering to a query.

    This joins with DocumentByConnectorCredentialPair and ConnectorCredentialPair to:
    1. Check if the document is from a PUBLIC connector (access_type = PUBLIC)
    2. Check private connector ownership and current internal group membership
    3. Check document-level permissions (is_public, external_user_emails, external_user_group_ids)
    4. Exclude documents from cc_pairs that are being deleted

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
        user_id = (
            select(User.__table__.c.id)
            .where(User.__table__.c.email == user_email)
            .scalar_subquery()
        )
        # Private connectors use Onyx ownership/groups, so their indexed files
        # need not have source-level external permission fields.
        owns_credential = (
            exists()
            .where(
                Credential.id == ConnectorCredentialPair.credential_id,
                Credential.user_id == user_id,
            )
            .correlate(ConnectorCredentialPair)
        )
        belongs_to_connector_group = (
            select(UserGroup__ConnectorCredentialPair.cc_pair_id)
            .join(
                User__UserGroup,
                User__UserGroup.user_group_id
                == UserGroup__ConnectorCredentialPair.user_group_id,
            )
            .where(
                UserGroup__ConnectorCredentialPair.cc_pair_id
                == ConnectorCredentialPair.id,
                UserGroup__ConnectorCredentialPair.is_current.is_(True),
                User__UserGroup.user_id == user_id,
            )
            .correlate(ConnectorCredentialPair)
            .exists()
        )
        access_filters.append(
            and_(
                ConnectorCredentialPair.access_type == AccessType.PRIVATE,
                or_(owns_credential, belongs_to_connector_group),
            )
        )
    if external_group_ids:
        access_filters.append(
            Document.external_user_group_ids.overlap(
                cast(postgresql.array(external_group_ids), postgresql.ARRAY(String))
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
    - Documents from PRIVATE connectors owned by the user or assigned to their groups
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
