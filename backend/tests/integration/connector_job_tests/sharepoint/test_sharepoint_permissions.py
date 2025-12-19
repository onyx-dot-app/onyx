import os

import pytest

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.utils.logger import setup_logger
from tests.integration.common_utils.document_acl import (
    get_all_connector_documents,
)
from tests.integration.common_utils.document_acl import (
    get_documents_by_permission_type,
)
from tests.integration.common_utils.document_acl import (
    get_user_document_access_via_acl,
)
from tests.integration.connector_job_tests.sharepoint.conftest import (
    SharepointTestEnvSetupTuple,
)

logger = setup_logger()


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
