"""
Utilities for testing document access control lists (ACLs) and permissions.
"""

from typing import List
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ee.onyx.access.access import _get_access_for_documents
from ee.onyx.db.external_perm import fetch_external_groups_for_user
from onyx.access.utils import prefix_external_group
from onyx.access.utils import prefix_user_email
from onyx.configs.constants import PUBLIC_DOC_PAT
from onyx.db.models import DocumentByConnectorCredentialPair
from onyx.db.models import User
from onyx.db.users import fetch_user_by_id
from onyx.utils.logger import setup_logger
from tests.integration.common_utils.test_models import DATestCCPair
from tests.integration.common_utils.test_models import DATestUser

logger = setup_logger()


def get_user_acl(user: User, db_session: Session) -> set[str]:
    """
    Get the ACL entries for a user, including their external groups, email, and public doc pattern.

    Args:
        user: The user object
        db_session: Database session

    Returns:
        Set of ACL entries for the user
    """
    db_external_groups = (
        fetch_external_groups_for_user(db_session, user.id) if user else []
    )
    prefixed_external_groups = [
        prefix_external_group(db_external_group.external_user_group_id)
        for db_external_group in db_external_groups
    ]

    user_acl = set(prefixed_external_groups)
    user_acl.update({prefix_user_email(user.email), PUBLIC_DOC_PAT})
    return user_acl


def get_user_document_access_via_acl(
    test_user: DATestUser, document_ids: List[str], db_session: Session
) -> List[str]:
    """
    Determine which documents a user can access by comparing user ACL with document ACLs.

    This is a more reliable method than search-based verification as it directly checks
    permission logic without depending on search relevance or ranking.

    Args:
        test_user: The test user to check access for
        document_ids: List of document IDs to check
        db_session: Database session

    Returns:
        List of document IDs that the user can access
    """
    # Get the actual User object from the database
    user = fetch_user_by_id(db_session, UUID(test_user.id))
    if not user:
        logger.error(f"Could not find user with ID {test_user.id}")
        return []

    user_acl = get_user_acl(user, db_session)
    logger.info(f"User {user.email} ACL entries: {user_acl}")

    # Get document access information
    doc_access_map = _get_access_for_documents(document_ids, db_session)
    logger.info(f"Found access info for {len(doc_access_map)} documents")

    accessible_docs = []
    for doc_id, doc_access in doc_access_map.items():
        doc_acl = doc_access.to_acl()
        logger.info(f"Document {doc_id} ACL: {doc_acl}")

        # Check if user has any matching ACL entry
        if user_acl.intersection(doc_acl):
            accessible_docs.append(doc_id)
            logger.info(f"User {user.email} has access to document {doc_id}")
        else:
            logger.info(f"User {user.email} does NOT have access to document {doc_id}")

    return accessible_docs


def get_all_connector_documents(
    cc_pair: DATestCCPair, db_session: Session
) -> List[str]:
    """
    Get all document IDs for a given connector/credential pair.

    Args:
        cc_pair: The connector-credential pair
        db_session: Database session

    Returns:
        List of document IDs
    """
    stmt = select(DocumentByConnectorCredentialPair.id).where(
        DocumentByConnectorCredentialPair.connector_id == cc_pair.connector_id,
        DocumentByConnectorCredentialPair.credential_id == cc_pair.credential_id,
    )

    result = db_session.execute(stmt)
    document_ids = [row[0] for row in result.fetchall()]
    logger.info(
        f"Found {len(document_ids)} documents for connector {cc_pair.connector_id}"
    )

    return document_ids


def get_documents_by_permission_type(
    document_ids: List[str], db_session: Session
) -> List[str]:
    """
    Categorize documents by their permission types and return public documents.

    Args:
        document_ids: List of document IDs to check
        db_session: Database session

    Returns:
        List of document IDs that are public
    """
    doc_access_map = _get_access_for_documents(document_ids, db_session)

    public_docs = []

    for doc_id, doc_access in doc_access_map.items():
        if doc_access.is_public:
            public_docs.append(doc_id)

    return public_docs
