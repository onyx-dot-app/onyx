import time
import uuid

import httpx

from onyx.background.celery.tasks.docprocessing.utils import (
    NUM_REPEAT_ERRORS_BEFORE_REPEATED_ERROR_STATE,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.mock_connector.connector import MockConnectorCheckpoint
from onyx.connectors.models import InputType
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import IndexingStatus
from tests.integration.common_utils.constants import MOCK_CONNECTOR_SERVER_HOST
from tests.integration.common_utils.constants import MOCK_CONNECTOR_SERVER_PORT
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.document import DocumentManager
from tests.integration.common_utils.managers.index_attempt import IndexAttemptManager
from tests.integration.common_utils.test_document_utils import create_test_document
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.common_utils.vespa import vespa_fixture


def test_repeated_error_state_detection_and_recovery(
    mock_server_client: httpx.Client,
    vespa_client: vespa_fixture,
    admin_user: DATestUser,
) -> None:
    """Test that a connector is marked as in a repeated error state after
    NUM_REPEAT_ERRORS_BEFORE_REPEATED_ERROR_STATE consecutive failures, and
    that it recovers after a successful indexing.

    This test ensures we properly wait for the required number of indexing attempts
    to fail before checking that the connector is in a repeated error state."""

    # Create test document for successful response
    test_doc = create_test_document()

    # First, set up the mock server to consistently fail
    error_response = {
        "documents": [],
        "checkpoint": MockConnectorCheckpoint(has_more=False).model_dump(mode="json"),
        "failures": [],
        "unhandled_exception": "Simulated unhandled error for testing repeated errors",
    }

    # Create a list of failure responses with at least the same length
    # as NUM_REPEAT_ERRORS_BEFORE_REPEATED_ERROR_STATE
    failure_behaviors = [error_response] * (
        5 * NUM_REPEAT_ERRORS_BEFORE_REPEATED_ERROR_STATE
    )

    response = mock_server_client.post(
        "/set-behavior",
        json=failure_behaviors,
    )
    assert response.status_code == 200

    # Create a new CC pair for testing
    cc_pair = CCPairManager.create_from_scratch(
        name=f"mock-repeated-error-{uuid.uuid4()}",
        source=DocumentSource.MOCK_CONNECTOR,
        input_type=InputType.POLL,
        connector_specific_config={
            "mock_server_host": MOCK_CONNECTOR_SERVER_HOST,
            "mock_server_port": MOCK_CONNECTOR_SERVER_PORT,
        },
        user_performing_action=admin_user,
        refresh_freq=60 * 60,  # a very long time
    )

    # Wait for the required number of failed indexing attempts
    # This shouldn't take long, since we keep retrying while we haven't
    # succeeded yet
    start_time = time.monotonic()
    while True:
        index_attempts_page = IndexAttemptManager.get_index_attempt_page(
            cc_pair_id=cc_pair.id,
            page=0,
            page_size=100,
            user_performing_action=admin_user,
        )
        index_attempts = [
            ia
            for ia in index_attempts_page.items
            if ia.status and ia.status.is_terminal()
        ]
        if len(index_attempts) >= NUM_REPEAT_ERRORS_BEFORE_REPEATED_ERROR_STATE:
            break

        if time.monotonic() - start_time > 180:
            raise TimeoutError(
                "Did not get required number of failed attempts within 180 seconds"
            )

        # make sure that we don't mark the connector as in repeated error state
        # before we have the required number of failed attempts
        with get_session_with_current_tenant() as db_session:
            cc_pair_obj = get_connector_credential_pair_from_id(
                db_session=db_session,
                cc_pair_id=cc_pair.id,
            )
            assert cc_pair_obj is not None
        assert not cc_pair_obj.in_repeated_error_state

        time.sleep(2)

    # Verify we have the correct number of failed attempts
    assert len(index_attempts) == NUM_REPEAT_ERRORS_BEFORE_REPEATED_ERROR_STATE
    for attempt in index_attempts:
        assert attempt.status == IndexingStatus.FAILED

    # Check if the connector is in a repeated error state
    start_time = time.monotonic()
    while True:
        with get_session_with_current_tenant() as db_session:
            cc_pair_obj = get_connector_credential_pair_from_id(
                db_session=db_session,
                cc_pair_id=cc_pair.id,
            )
            assert cc_pair_obj is not None
            if cc_pair_obj.in_repeated_error_state:
                break

        if time.monotonic() - start_time > 30:
            assert False, "CC pair did not enter repeated error state within 30 seconds"

        time.sleep(2)

    # Reset the mock server state
    response = mock_server_client.post("/reset")
    assert response.status_code == 200

    # Now set up the mock server to succeed
    success_response = {
        "documents": [test_doc.model_dump(mode="json")],
        "checkpoint": MockConnectorCheckpoint(has_more=False).model_dump(mode="json"),
        "failures": [],
    }

    response = mock_server_client.post(
        "/set-behavior",
        json=[success_response],
    )
    assert response.status_code == 200

    # Run another indexing attempt that should succeed
    CCPairManager.run_once(
        cc_pair, from_beginning=True, user_performing_action=admin_user
    )

    recovery_index_attempt = IndexAttemptManager.wait_for_index_attempt_start(
        cc_pair_id=cc_pair.id,
        index_attempts_to_ignore=[index_attempt.id for index_attempt in index_attempts],
        user_performing_action=admin_user,
    )

    IndexAttemptManager.wait_for_index_attempt_completion(
        index_attempt_id=recovery_index_attempt.id,
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )

    # Validate the indexing succeeded
    finished_recovery_attempt = IndexAttemptManager.get_index_attempt_by_id(
        index_attempt_id=recovery_index_attempt.id,
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )
    assert finished_recovery_attempt.status == IndexingStatus.SUCCESS

    # Verify the document was indexed
    with get_session_with_current_tenant() as db_session:
        documents = DocumentManager.fetch_documents_for_cc_pair(
            cc_pair_id=cc_pair.id,
            db_session=db_session,
            vespa_client=vespa_client,
        )
    assert len(documents) == 1
    assert documents[0].id == test_doc.id

    # Verify the CC pair is no longer in a repeated error state
    start = time.monotonic()
    while True:
        with get_session_with_current_tenant() as db_session:
            cc_pair_obj = get_connector_credential_pair_from_id(
                db_session=db_session,
                cc_pair_id=cc_pair.id,
            )
            assert cc_pair_obj is not None
            if not cc_pair_obj.in_repeated_error_state:
                break

        elapsed = time.monotonic() - start
        if elapsed > 30:
            raise TimeoutError(
                "CC pair did not exit repeated error state within 30 seconds"
            )

        print(
            f"Waiting for CC pair to exit repeated error state. elapsed={elapsed:.2f}"
        )
        time.sleep(1)
