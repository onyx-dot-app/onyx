import os
from typing import List
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from ee.onyx.access.access import _get_access_for_documents
from ee.onyx.db.external_perm import fetch_external_groups_for_user
from onyx.access.utils import prefix_external_group
from onyx.access.utils import prefix_user_email
from onyx.configs.constants import PUBLIC_DOC_PAT
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import User
from onyx.db.users import fetch_user_by_id
from onyx.utils.logger import setup_logger
from tests.integration.common_utils.test_models import DATestCCPair
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.connector_job_tests.sharepoint.conftest import (
    SharepointTestEnvSetupTuple,
)

logger = setup_logger()


def get_user_acl(user: User, db_session: Session) -> set[str]:
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
    from onyx.db.models import DocumentByConnectorCredentialPair
    from sqlalchemy import select

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
    Categorize documents by their permission types
    Returns a dictionary with lists of document IDs for each permission type
    """
    doc_access_map = _get_access_for_documents(document_ids, db_session)

    public_docs = []

    for doc_id, doc_access in doc_access_map.items():
        if doc_access.is_public:
            public_docs.append(doc_id)

    return public_docs


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Permission tests are enterprise only",
)
def test_public_documents_accessible_by_all_users(
    sharepoint_test_env_setup: SharepointTestEnvSetupTuple,
) -> None:
    """Test that public documents are accessible by both test users using ACL verification"""
    (
        admin_user,
        regular_user_1,
        regular_user_2,
        credential,
        connector,
        cc_pair,
    ) = sharepoint_test_env_setup

    with get_session_with_current_tenant() as db_session:
        # Get all documents for this connector
        all_document_ids = get_all_connector_documents(cc_pair, db_session)

        # Test that regular_user_1 can access documents
        accessible_docs_user1 = get_user_document_access_via_acl(
            test_user=regular_user_1,
            document_ids=all_document_ids,
            db_session=db_session,
        )

        # Test that regular_user_2 can access documents
        accessible_docs_user2 = get_user_document_access_via_acl(
            test_user=regular_user_2,
            document_ids=all_document_ids,
            db_session=db_session,
        )

        logger.info(f"User 1 has access to {len(accessible_docs_user1)} documents")
        logger.info(f"User 2 has access to {len(accessible_docs_user2)} documents")

        # For public documents, both users should have access to at least some docs
        assert len(accessible_docs_user1) == 8, (
            f"User 1 should have access to documents. Found "
            f"{len(accessible_docs_user1)} accessible docs out of "
            f"{len(all_document_ids)} total"
        )
        assert len(accessible_docs_user2) == 1, (
            f"User 2 should have access to documents. Found "
            f"{len(accessible_docs_user2)} accessible docs out of "
            f"{len(all_document_ids)} total"
        )

        logger.info(
            "Successfully verified public documents are accessible by users via ACL"
        )


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Permission tests are enterprise only",
)
def test_group_based_permissions(
    sharepoint_test_env_setup: SharepointTestEnvSetupTuple,
) -> None:
    """Test that documents with group permissions are accessible only by users in that group using ACL verification"""
    (
        admin_user,
        regular_user_1,
        regular_user_2,
        credential,
        connector,
        cc_pair,
    ) = sharepoint_test_env_setup

    with get_session_with_current_tenant() as db_session:
        # Get all documents for this connector
        all_document_ids = get_all_connector_documents(cc_pair, db_session)

        if not all_document_ids:
            pytest.skip("No documents found for connector - skipping test")

        # Test access for both users
        accessible_docs_user1 = get_user_document_access_via_acl(
            test_user=regular_user_1,
            document_ids=all_document_ids,
            db_session=db_session,
        )

        accessible_docs_user2 = get_user_document_access_via_acl(
            test_user=regular_user_2,
            document_ids=all_document_ids,
            db_session=db_session,
        )

        logger.info(f"User 1 has access to {len(accessible_docs_user1)} documents")
        logger.info(f"User 2 has access to {len(accessible_docs_user2)} documents")

        public_docs = get_documents_by_permission_type(all_document_ids, db_session)

        # Check if user 2 has access to any non-public documents
        non_public_access_user2 = [
            doc for doc in accessible_docs_user2 if doc not in public_docs
        ]

        assert (
            len(non_public_access_user2) == 0
        ), f"User 2 should only have access to public documents. Found access to non-public docs: {non_public_access_user2}"
