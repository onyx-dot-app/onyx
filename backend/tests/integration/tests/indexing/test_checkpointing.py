import uuid
from datetime import datetime
from datetime import timedelta
from datetime import timezone

import httpx

from onyx.configs.constants import DocumentSource
from onyx.connectors.mock_connector.connector import MockConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import EntityFailure
from onyx.connectors.models import InputType
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import IndexingStatus
from tests.integration.common_utils.constants import MOCK_CONNECTOR_SERVER_HOST
from tests.integration.common_utils.constants import MOCK_CONNECTOR_SERVER_PORT
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.document import DocumentManager
from tests.integration.common_utils.managers.index_attempt import IndexAttemptManager
from tests.integration.common_utils.test_document_utils import create_test_document
from tests.integration.common_utils.test_document_utils import (
    create_test_document_failure,
)
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.common_utils.vespa import vespa_fixture


def test_mock_connector_basic_flow(
    mock_server_client: httpx.Client,
    vespa_client: vespa_fixture,
    admin_user: DATestUser,
) -> None:
    """Test that the mock connector can successfully process documents and failures"""
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

    # create CC Pair + index attempt
    cc_pair = CCPairManager.create_from_scratch(
        name=f"mock-connector-{uuid.uuid4()}",
        source=DocumentSource.MOCK_CONNECTOR,
        input_type=InputType.POLL,
        connector_specific_config={
            "mock_server_host": MOCK_CONNECTOR_SERVER_HOST,
            "mock_server_port": MOCK_CONNECTOR_SERVER_PORT,
        },
        user_performing_action=admin_user,
    )

    # wait for index attempt to start
    index_attempt = IndexAttemptManager.wait_for_index_attempt_start(
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )

    # wait for index attempt to finish
    IndexAttemptManager.wait_for_index_attempt_completion(
        index_attempt_id=index_attempt.id,
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )

    # validate status
    finished_index_attempt = IndexAttemptManager.get_index_attempt_by_id(
        index_attempt_id=index_attempt.id,
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )
    assert finished_index_attempt.status == IndexingStatus.SUCCESS

    # Verify results
    with get_session_with_current_tenant() as db_session:
        chunks = DocumentManager.fetch_documents_for_cc_pair(
            cc_pair_id=cc_pair.id,
            db_session=db_session,
            vespa_client=vespa_client,
        )
    assert len(chunks) == 1
    assert chunks[0].id == test_doc.id

    errors = IndexAttemptManager.get_index_attempt_errors_for_cc_pair(
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )
    assert len(errors) == 0


def test_mock_connector_with_failures(
    mock_server_client: httpx.Client,
    vespa_client: vespa_fixture,
    admin_user: DATestUser,
) -> None:
    """Test that the mock connector processes both successes and failures properly."""
    doc1 = create_test_document()
    doc2 = create_test_document()
    doc2_failure = create_test_document_failure(doc_id=doc2.id)

    response = mock_server_client.post(
        "/set-behavior",
        json=[
            {
                "documents": [doc1.model_dump(mode="json")],
                "checkpoint": MockConnectorCheckpoint(has_more=False).model_dump(
                    mode="json"
                ),
                "failures": [doc2_failure.model_dump(mode="json")],
            }
        ],
    )
    assert response.status_code == 200

    # Create a CC Pair for the mock connector
    cc_pair = CCPairManager.create_from_scratch(
        name=f"mock-connector-failure-{uuid.uuid4()}",
        source=DocumentSource.MOCK_CONNECTOR,
        input_type=InputType.POLL,
        connector_specific_config={
            "mock_server_host": MOCK_CONNECTOR_SERVER_HOST,
            "mock_server_port": MOCK_CONNECTOR_SERVER_PORT,
        },
        user_performing_action=admin_user,
    )

    # Wait for the index attempt to start and then complete
    index_attempt = IndexAttemptManager.wait_for_index_attempt_start(
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )

    IndexAttemptManager.wait_for_index_attempt_completion(
        index_attempt_id=index_attempt.id,
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )

    # validate status
    finished_index_attempt = IndexAttemptManager.get_index_attempt_by_id(
        index_attempt_id=index_attempt.id,
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )
    assert finished_index_attempt.status == IndexingStatus.COMPLETED_WITH_ERRORS

    # Verify results: doc1 should be indexed and doc2 should have an error entry
    with get_session_with_current_tenant() as db_session:
        documents = DocumentManager.fetch_documents_for_cc_pair(
            cc_pair_id=cc_pair.id,
            db_session=db_session,
            vespa_client=vespa_client,
        )
    assert len(documents) == 1
    assert documents[0].id == doc1.id

    errors = IndexAttemptManager.get_index_attempt_errors_for_cc_pair(
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )
    assert len(errors) == 1
    error = errors[0]
    assert error.failure_message == doc2_failure.failure_message
    assert error.document_id == doc2.id


def test_mock_connector_failure_recovery(
    mock_server_client: httpx.Client,
    vespa_client: vespa_fixture,
    admin_user: DATestUser,
) -> None:
    """Test that a failed document can be successfully indexed in a subsequent attempt
    while maintaining previously successful documents."""
    # Create test documents and failure
    doc1 = create_test_document()
    doc2 = create_test_document()
    doc2_failure = create_test_document_failure(doc_id=doc2.id)
    entity_id = "test-entity-id"
    entity_failure_msg = "Simulated unhandled error"

    response = mock_server_client.post(
        "/set-behavior",
        json=[
            {
                "documents": [doc1.model_dump(mode="json")],
                "checkpoint": MockConnectorCheckpoint(has_more=False).model_dump(
                    mode="json"
                ),
                "failures": [
                    doc2_failure.model_dump(mode="json"),
                    ConnectorFailure(
                        failed_entity=EntityFailure(
                            entity_id=entity_id,
                            missed_time_range=(
                                datetime.now(timezone.utc) - timedelta(days=1),
                                datetime.now(timezone.utc),
                            ),
                        ),
                        failure_message=entity_failure_msg,
                    ).model_dump(mode="json"),
                ],
            }
        ],
    )
    assert response.status_code == 200

    # Create CC Pair and run initial indexing attempt
    cc_pair = CCPairManager.create_from_scratch(
        name=f"mock-connector-{uuid.uuid4()}",
        source=DocumentSource.MOCK_CONNECTOR,
        input_type=InputType.POLL,
        connector_specific_config={
            "mock_server_host": MOCK_CONNECTOR_SERVER_HOST,
            "mock_server_port": MOCK_CONNECTOR_SERVER_PORT,
        },
        user_performing_action=admin_user,
    )

    # Wait for first index attempt to complete
    initial_index_attempt = IndexAttemptManager.wait_for_index_attempt_start(
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )
    IndexAttemptManager.wait_for_index_attempt_completion(
        index_attempt_id=initial_index_attempt.id,
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )

    # validate status
    finished_index_attempt = IndexAttemptManager.get_index_attempt_by_id(
        index_attempt_id=initial_index_attempt.id,
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )
    assert finished_index_attempt.status == IndexingStatus.COMPLETED_WITH_ERRORS

    # Verify initial state: doc1 indexed, doc2 failed
    with get_session_with_current_tenant() as db_session:
        documents = DocumentManager.fetch_documents_for_cc_pair(
            cc_pair_id=cc_pair.id,
            db_session=db_session,
            vespa_client=vespa_client,
        )
    assert len(documents) == 1
    assert documents[0].id == doc1.id

    errors = IndexAttemptManager.get_index_attempt_errors_for_cc_pair(
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )
    assert len(errors) == 2
    error_doc2 = next(error for error in errors if error.document_id == doc2.id)
    assert error_doc2.failure_message == doc2_failure.failure_message
    assert not error_doc2.is_resolved

    error_entity = next(error for error in errors if error.entity_id == entity_id)
    assert error_entity.failure_message == entity_failure_msg
    assert not error_entity.is_resolved

    # Update mock server to return success for both documents
    response = mock_server_client.post(
        "/set-behavior",
        json=[
            {
                "documents": [
                    doc1.model_dump(mode="json"),
                    doc2.model_dump(mode="json"),
                ],
                "checkpoint": MockConnectorCheckpoint(has_more=False).model_dump(
                    mode="json"
                ),
                "failures": [],
            }
        ],
    )
    assert response.status_code == 200

    # Trigger another indexing attempt
    # NOTE: must be from beginning to handle the entity failure
    CCPairManager.run_once(
        cc_pair, from_beginning=True, user_performing_action=admin_user
    )
    recovery_index_attempt = IndexAttemptManager.wait_for_index_attempt_start(
        cc_pair_id=cc_pair.id,
        index_attempts_to_ignore=[initial_index_attempt.id],
        user_performing_action=admin_user,
    )
    IndexAttemptManager.wait_for_index_attempt_completion(
        index_attempt_id=recovery_index_attempt.id,
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )

    finished_second_index_attempt = IndexAttemptManager.get_index_attempt_by_id(
        index_attempt_id=recovery_index_attempt.id,
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )
    assert finished_second_index_attempt.status == IndexingStatus.SUCCESS

    # Verify both documents are now indexed
    with get_session_with_current_tenant() as db_session:
        documents = DocumentManager.fetch_documents_for_cc_pair(
            cc_pair_id=cc_pair.id,
            db_session=db_session,
            vespa_client=vespa_client,
        )
    assert len(documents) == 2
    document_ids = {doc.id for doc in documents}
    assert doc2.id in document_ids
    assert doc1.id in document_ids

    # Verify original failures were marked as resolved
    errors = IndexAttemptManager.get_index_attempt_errors_for_cc_pair(
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )
    assert len(errors) == 2
    error_doc2 = next(error for error in errors if error.document_id == doc2.id)
    error_entity = next(error for error in errors if error.entity_id == entity_id)

    assert error_doc2.is_resolved
    assert error_entity.is_resolved


def test_mock_connector_checkpoint_recovery(
    mock_server_client: httpx.Client,
    vespa_client: vespa_fixture,
    admin_user: DATestUser,
) -> None:
    """Test that checkpointing works correctly when an unhandled exception occurs
    and that subsequent runs pick up from the last successful checkpoint."""
    # Create test documents
    docs_batch_1 = [create_test_document() for _ in range(100)]
    doc2 = create_test_document()
    doc3 = create_test_document()

    # Set up mock server behavior for initial run:
    # - First yield: 100 docs with checkpoint1
    # - Second yield: doc2 with checkpoint2
    # - Third yield: unhandled exception
    response = mock_server_client.post(
        "/set-behavior",
        json=[
            {
                "documents": [doc.model_dump(mode="json") for doc in docs_batch_1],
                "checkpoint": MockConnectorCheckpoint(
                    has_more=True, last_document_id=docs_batch_1[-1].id
                ).model_dump(mode="json"),
                "failures": [],
            },
            {
                "documents": [doc2.model_dump(mode="json")],
                "checkpoint": MockConnectorCheckpoint(
                    has_more=True, last_document_id=doc2.id
                ).model_dump(mode="json"),
                "failures": [],
            },
            {
                "documents": [],
                # should never hit this, unhandled exception happens first
                "checkpoint": MockConnectorCheckpoint(
                    has_more=False, last_document_id=doc2.id
                ).model_dump(mode="json"),
                "failures": [],
                "unhandled_exception": "Simulated unhandled error",
            },
        ],
    )
    assert response.status_code == 200

    # Create CC Pair and run initial indexing attempt
    cc_pair = CCPairManager.create_from_scratch(
        name=f"mock-connector-checkpoint-{uuid.uuid4()}",
        source=DocumentSource.MOCK_CONNECTOR,
        input_type=InputType.POLL,
        connector_specific_config={
            "mock_server_host": MOCK_CONNECTOR_SERVER_HOST,
            "mock_server_port": MOCK_CONNECTOR_SERVER_PORT,
        },
        user_performing_action=admin_user,
    )

    # Wait for first index attempt to complete
    initial_index_attempt = IndexAttemptManager.wait_for_index_attempt_start(
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )
    IndexAttemptManager.wait_for_index_attempt_completion(
        index_attempt_id=initial_index_attempt.id,
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )

    # validate status
    finished_index_attempt = IndexAttemptManager.get_index_attempt_by_id(
        index_attempt_id=initial_index_attempt.id,
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )
    assert finished_index_attempt.status == IndexingStatus.FAILED

    # Verify initial state: both docs should be indexed
    with get_session_with_current_tenant() as db_session:
        documents = DocumentManager.fetch_documents_for_cc_pair(
            cc_pair_id=cc_pair.id,
            db_session=db_session,
            vespa_client=vespa_client,
        )
    # This is no longer guaranteed because docfetching and docprocessing are decoupled!
    # Some batches may not be processed when docfetching fails, but they should still stick around
    # in the filestore and be ready for the next run.
    # assert len(documents) == 101  # 100 docs from first batch + doc2
    # document_ids = {doc.id for doc in documents}
    # assert doc2.id in document_ids
    # assert all(doc.id in document_ids for doc in docs_batch_1)

    # Get the checkpoints that were sent to the mock server
    response = mock_server_client.get("/get-checkpoints")
    assert response.status_code == 200
    initial_checkpoints = response.json()

    # Verify we got the expected checkpoints in order
    assert len(initial_checkpoints) == 3
    assert initial_checkpoints[0] == {
        "has_more": True,
        "last_document_id": None,
    }  # Initial empty checkpoint
    assert initial_checkpoints[1] == {
        "has_more": True,
        "last_document_id": docs_batch_1[-1].id,
    }
    assert initial_checkpoints[2] == {"has_more": True, "last_document_id": doc2.id}

    # Reset the mock server for the next run
    response = mock_server_client.post("/reset")
    assert response.status_code == 200

    # Set up mock server behavior for recovery run - should succeed fully this time
    response = mock_server_client.post(
        "/set-behavior",
        json=[
            {
                "documents": [doc3.model_dump(mode="json")],
                "checkpoint": MockConnectorCheckpoint(
                    has_more=False, last_document_id=doc3.id
                ).model_dump(mode="json"),
                "failures": [],
            }
        ],
    )
    assert response.status_code == 200

    # Trigger another indexing attempt
    CCPairManager.run_once(
        cc_pair, from_beginning=False, user_performing_action=admin_user
    )
    recovery_index_attempt = IndexAttemptManager.wait_for_index_attempt_start(
        cc_pair_id=cc_pair.id,
        index_attempts_to_ignore=[initial_index_attempt.id],
        user_performing_action=admin_user,
    )
    IndexAttemptManager.wait_for_index_attempt_completion(
        index_attempt_id=recovery_index_attempt.id,
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )

    # validate status
    finished_recovery_attempt = IndexAttemptManager.get_index_attempt_by_id(
        index_attempt_id=recovery_index_attempt.id,
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )
    assert finished_recovery_attempt.status == IndexingStatus.SUCCESS

    # Verify results
    with get_session_with_current_tenant() as db_session:
        documents = DocumentManager.fetch_documents_for_cc_pair(
            cc_pair_id=cc_pair.id,
            db_session=db_session,
            vespa_client=vespa_client,
        )
    assert len(documents) == 102  # 100 docs from first batch + doc2 + doc3
    document_ids = {doc.id for doc in documents}
    assert doc3.id in document_ids
    assert doc2.id in document_ids
    assert all(doc.id in document_ids for doc in docs_batch_1)

    # Get the checkpoints from the recovery run
    response = mock_server_client.get("/get-checkpoints")
    assert response.status_code == 200
    recovery_checkpoints = response.json()

    # Verify the recovery run started from the last successful checkpoint
    assert len(recovery_checkpoints) == 1
    assert recovery_checkpoints[0] == {"has_more": True, "last_document_id": doc2.id}
