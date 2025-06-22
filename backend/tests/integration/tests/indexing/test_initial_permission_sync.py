import os
import uuid

import httpx
import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.mock_connector.connector import EXTERNAL_USER_EMAILS
from onyx.connectors.mock_connector.connector import EXTERNAL_USER_GROUP_IDS
from onyx.connectors.mock_connector.connector import MockConnectorCheckpoint
from onyx.connectors.models import InputType
from onyx.db.document import get_documents_by_ids
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccessType
from onyx.db.enums import IndexingStatus
from tests.integration.common_utils.constants import MOCK_CONNECTOR_SERVER_HOST
from tests.integration.common_utils.constants import MOCK_CONNECTOR_SERVER_PORT
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.document import DocumentManager
from tests.integration.common_utils.managers.index_attempt import IndexAttemptManager
from tests.integration.common_utils.test_document_utils import create_test_document
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.common_utils.vespa import vespa_fixture


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Permission sync is enterprise only",
)
def test_mock_connector_initial_permission_sync(
    mock_server_client: httpx.Client,
    vespa_client: vespa_fixture,
    admin_user: DATestUser,
) -> None:
    """Test that the MockConnector fetches and sets permissions during initial indexing when AccessType.SYNC is used"""

    # Set up mock server behavior
    doc_uuid = uuid.uuid4()
    test_doc = create_test_document(doc_id=f"test-doc-{doc_uuid}")

    response = mock_server_client.post(
        "/set-behavior",
        json=[
            {
                "documents": [test_doc.model_dump(mode="json")],
                "checkpoint": MockConnectorCheckpoint(has_more=False).model_dump(
                    mode="json"
                ),
                "failures": [],
            }
        ],
    )
    assert response.status_code == 200

    # Create CC Pair with SYNC access type to enable permissions during indexing
    cc_pair = CCPairManager.create_from_scratch(
        name=f"mock-connector-permissions-{uuid.uuid4()}",
        source=DocumentSource.MOCK_CONNECTOR,
        input_type=InputType.POLL,
        connector_specific_config={
            "mock_server_host": MOCK_CONNECTOR_SERVER_HOST,
            "mock_server_port": MOCK_CONNECTOR_SERVER_PORT,
        },
        access_type=AccessType.SYNC,  # This enables permissions during indexing
        user_performing_action=admin_user,
    )

    # Wait for index attempt to start
    index_attempt = IndexAttemptManager.wait_for_index_attempt_start(
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )

    # Wait for index attempt to finish
    IndexAttemptManager.wait_for_index_attempt_completion(
        index_attempt_id=index_attempt.id,
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )

    # Validate status
    finished_index_attempt = IndexAttemptManager.get_index_attempt_by_id(
        index_attempt_id=index_attempt.id,
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )
    assert finished_index_attempt.status == IndexingStatus.SUCCESS

    # Verify document was indexed
    with get_session_with_current_tenant() as db_session:
        documents = DocumentManager.fetch_documents_for_cc_pair(
            cc_pair_id=cc_pair.id,
            db_session=db_session,
            vespa_client=vespa_client,
        )
    assert len(documents) == 1
    assert documents[0].id == test_doc.id

    # Verify no errors occurred
    errors = IndexAttemptManager.get_index_attempt_errors_for_cc_pair(
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )
    assert len(errors) == 0

    # Verify permissions were set during indexing by checking the document in the database
    with get_session_with_current_tenant() as db_session:
        db_docs = get_documents_by_ids(
            db_session=db_session,
            document_ids=[test_doc.id],
        )
        assert len(db_docs) == 1
        db_doc = db_docs[0]

        assert db_doc.external_user_emails is not None
        assert db_doc.external_user_group_ids is not None

        # Check the specific permissions that MockConnector sets
        assert set(db_doc.external_user_emails) == EXTERNAL_USER_EMAILS
        assert set(db_doc.external_user_group_ids) == EXTERNAL_USER_GROUP_IDS

        # Verify the document is not public (as set by MockConnector)
        assert db_doc.is_public is False

    # Verify that the cc_pair was marked as permissions synced
    updated_cc_pair_info = CCPairManager.get_single(
        cc_pair.id, user_performing_action=admin_user
    )
    assert updated_cc_pair_info is not None
    assert updated_cc_pair_info.last_full_permission_sync is not None
