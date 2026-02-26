import os
import uuid
from datetime import datetime
from datetime import timezone

import httpx
import pytest
from sqlalchemy import select

from onyx.configs.constants import DocumentSource
from onyx.connectors.mock_connector.connector import EXTERNAL_USER_EMAILS
from onyx.connectors.mock_connector.connector import EXTERNAL_USER_GROUP_IDS
from onyx.connectors.mock_connector.connector import MockConnectorCheckpoint
from onyx.connectors.models import Document
from onyx.connectors.models import InputType
from onyx.db.document import get_documents_by_ids
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccessType
from onyx.db.enums import IndexingStatus
from onyx.db.enums import PermissionSyncStatus
from onyx.db.models import DocPermissionSyncAttempt
from tests.integration.common_utils.constants import MOCK_CONNECTOR_SERVER_HOST
from tests.integration.common_utils.constants import MOCK_CONNECTOR_SERVER_PORT
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.document import DocumentManager
from tests.integration.common_utils.managers.index_attempt import IndexAttemptManager
from tests.integration.common_utils.test_document_utils import create_test_document
from tests.integration.common_utils.test_models import DATestCCPair
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.common_utils.vespa import vespa_fixture


def _setup_mock_connector(
    mock_server_client: httpx.Client,
    admin_user: DATestUser,
) -> tuple[DATestCCPair, Document]:
    """Common setup: create a test doc, configure mock server, create cc_pair, wait for indexing."""
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

    cc_pair = CCPairManager.create_from_scratch(
        name=f"mock-connector-{uuid.uuid4()}",
        source=DocumentSource.MOCK_CONNECTOR,
        input_type=InputType.POLL,
        connector_specific_config={
            "mock_server_host": MOCK_CONNECTOR_SERVER_HOST,
            "mock_server_port": MOCK_CONNECTOR_SERVER_PORT,
        },
        access_type=AccessType.SYNC,
        user_performing_action=admin_user,
    )

    index_attempt = IndexAttemptManager.wait_for_index_attempt_start(
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )

    IndexAttemptManager.wait_for_index_attempt_completion(
        index_attempt_id=index_attempt.id,
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )

    finished = IndexAttemptManager.get_index_attempt_by_id(
        index_attempt_id=index_attempt.id,
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )
    assert finished.status == IndexingStatus.SUCCESS
    return cc_pair, test_doc


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Permission sync is enterprise only",
)
def test_mock_connector_initial_permission_sync(
    mock_server_client: httpx.Client,
    vespa_client: vespa_fixture,
    admin_user: DATestUser,
) -> None:
    """Test that the MockConnector fetches and sets permissions during initial indexing
    when AccessType.SYNC is used."""

    cc_pair, test_doc = _setup_mock_connector(mock_server_client, admin_user)

    with get_session_with_current_tenant() as db_session:
        documents = DocumentManager.fetch_documents_for_cc_pair(
            cc_pair_id=cc_pair.id,
            db_session=db_session,
            vespa_client=vespa_client,
        )
    assert len(documents) == 1
    assert documents[0].id == test_doc.id

    errors = IndexAttemptManager.get_index_attempt_errors_for_cc_pair(
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )
    assert len(errors) == 0

    with get_session_with_current_tenant() as db_session:
        db_docs = get_documents_by_ids(
            db_session=db_session,
            document_ids=[test_doc.id],
        )
        assert len(db_docs) == 1
        db_doc = db_docs[0]

        assert db_doc.external_user_emails is not None
        assert db_doc.external_user_group_ids is not None
        assert set(db_doc.external_user_emails) == EXTERNAL_USER_EMAILS
        assert set(db_doc.external_user_group_ids) == EXTERNAL_USER_GROUP_IDS
        assert db_doc.is_public is False

    # After initial indexing, the beat task detects last_time_perm_sync is None
    # and triggers a doc permission sync. Explicitly trigger it to avoid
    # waiting for the 30s beat interval.
    before = datetime.now(timezone.utc)
    CCPairManager.sync(
        cc_pair=cc_pair,
        user_performing_action=admin_user,
    )
    CCPairManager.wait_for_sync(
        cc_pair=cc_pair,
        after=before,
        number_of_updated_docs=1,
        user_performing_action=admin_user,
        should_wait_for_group_sync=False,
        should_wait_for_vespa_sync=False,
    )

    updated_cc_pair_info = CCPairManager.get_single(
        cc_pair.id, user_performing_action=admin_user
    )
    assert updated_cc_pair_info is not None
    assert updated_cc_pair_info.last_full_permission_sync is not None


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Permission sync attempt tracking is enterprise only",
)
def test_permission_sync_attempt_tracking_integration(
    mock_server_client: httpx.Client,
    vespa_client: vespa_fixture,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    """Test that permission sync attempts are properly tracked during real sync workflows."""

    cc_pair, _test_doc = _setup_mock_connector(mock_server_client, admin_user)

    before = datetime.now(timezone.utc)
    CCPairManager.sync(
        cc_pair=cc_pair,
        user_performing_action=admin_user,
    )

    CCPairManager.wait_for_sync(
        cc_pair=cc_pair,
        after=before,
        number_of_updated_docs=1,
        user_performing_action=admin_user,
        should_wait_for_group_sync=False,
        should_wait_for_vespa_sync=False,
    )

    with get_session_with_current_tenant() as db_session:
        attempt = db_session.execute(
            select(DocPermissionSyncAttempt).where(
                DocPermissionSyncAttempt.connector_credential_pair_id == cc_pair.id
            )
        ).scalar_one()

        assert attempt.status in [
            PermissionSyncStatus.SUCCESS,
            PermissionSyncStatus.COMPLETED_WITH_ERRORS,
            PermissionSyncStatus.FAILED,
        ]
        assert attempt.total_docs_synced is not None and attempt.total_docs_synced >= 0
        assert (
            attempt.docs_with_permission_errors is not None
            and attempt.docs_with_permission_errors >= 0
        )


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Permission sync attempt tracking is enterprise only",
)
def test_permission_sync_attempt_status_success(
    mock_server_client: httpx.Client,
    vespa_client: vespa_fixture,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    """Test that permission sync attempts are marked as SUCCESS when sync completes without errors."""

    cc_pair, _test_doc = _setup_mock_connector(mock_server_client, admin_user)

    before = datetime.now(timezone.utc)
    CCPairManager.sync(
        cc_pair=cc_pair,
        user_performing_action=admin_user,
    )

    CCPairManager.wait_for_sync(
        cc_pair=cc_pair,
        after=before,
        number_of_updated_docs=1,
        user_performing_action=admin_user,
        should_wait_for_group_sync=False,
        should_wait_for_vespa_sync=False,
    )

    with get_session_with_current_tenant() as db_session:
        attempt = db_session.execute(
            select(DocPermissionSyncAttempt).where(
                DocPermissionSyncAttempt.connector_credential_pair_id == cc_pair.id
            )
        ).scalar_one()

        assert attempt.status == PermissionSyncStatus.SUCCESS
        assert attempt.total_docs_synced is not None and attempt.total_docs_synced >= 0
        assert (
            attempt.docs_with_permission_errors is not None
            and attempt.docs_with_permission_errors == 0
        )
