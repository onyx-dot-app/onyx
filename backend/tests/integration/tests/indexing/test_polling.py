import uuid
from datetime import datetime
from datetime import timedelta
from datetime import timezone

import httpx

from onyx.configs.app_configs import POLL_CONNECTOR_OFFSET
from onyx.configs.constants import DocumentSource
from onyx.connectors.mock_connector.connector import MockConnectorCheckpoint
from onyx.connectors.models import InputType
from onyx.db.enums import IndexingStatus
from tests.integration.common_utils.constants import MOCK_CONNECTOR_SERVER_HOST
from tests.integration.common_utils.constants import MOCK_CONNECTOR_SERVER_PORT
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.index_attempt import IndexAttemptManager
from tests.integration.common_utils.test_document_utils import create_test_document
from tests.integration.common_utils.test_models import DATestUser


def _setup_mock_connector(
    mock_server_client: httpx.Client,
    admin_user: DATestUser,
) -> None:
    test_doc = create_test_document()
    successful_response = {
        "documents": [test_doc.model_dump(mode="json")],
        "checkpoint": MockConnectorCheckpoint(has_more=False).model_dump(mode="json"),
        "failures": [],
    }
    response = mock_server_client.post(
        "/set-behavior",
        json=[successful_response, successful_response],  # For two attempts
    )
    assert response.status_code == 200


def test_poll_connector_time_ranges(
    mock_server_client: httpx.Client,
    admin_user: DATestUser,
) -> None:
    """
    Tests that poll connectors correctly set their poll_range_start and poll_range_end
    across multiple indexing attempts.
    """
    # Set up mock server behavior - a simple successful response
    _setup_mock_connector(mock_server_client, admin_user)

    # Create a CC Pair for the mock connector with POLL input type
    cc_pair_name = f"mock-poll-time-range-{uuid.uuid4()}"
    cc_pair = CCPairManager.create_from_scratch(
        name=cc_pair_name,
        source=DocumentSource.MOCK_CONNECTOR,
        input_type=InputType.POLL,
        connector_specific_config={
            "mock_server_host": MOCK_CONNECTOR_SERVER_HOST,
            "mock_server_port": MOCK_CONNECTOR_SERVER_PORT,
        },
        user_performing_action=admin_user,
        refresh_freq=3,  # refresh often to ensure the second attempt actually runs
    )

    # --- First Indexing Attempt ---
    time_before_first_attempt = datetime.now(timezone.utc)
    first_index_attempt = IndexAttemptManager.wait_for_index_attempt_start(
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )
    IndexAttemptManager.wait_for_index_attempt_completion(
        index_attempt_id=first_index_attempt.id,
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )
    time_after_first_attempt = datetime.now(timezone.utc)

    # Fetch and validate the first attempt
    completed_first_attempt = IndexAttemptManager.get_index_attempt_by_id(
        index_attempt_id=first_index_attempt.id,
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )
    assert completed_first_attempt.status == IndexingStatus.SUCCESS
    assert completed_first_attempt.poll_range_start is not None
    assert completed_first_attempt.poll_range_end is not None

    # For the first run (no prior successful attempts), poll_range_start should be epoch (0)
    expected_first_start = datetime.fromtimestamp(0, tz=timezone.utc)
    assert completed_first_attempt.poll_range_start == expected_first_start

    # `poll_range_end` should be sometime in between the time the attempt
    # started and the time it finished.
    # no way to have a more precise assertion here since the `poll_range_end`
    # can really be set anytime in that range and be "correct"
    assert (
        time_before_first_attempt
        <= completed_first_attempt.poll_range_end
        <= time_after_first_attempt
    )

    first_attempt_poll_end = completed_first_attempt.poll_range_end

    # --- Second Indexing Attempt ---
    # Trigger another run manually (since automatic refresh might be too slow for test)
    # Ensure there's a slight delay so the poll window moves
    # In a real scenario, the scheduler would wait for the refresh frequency.
    # Here we manually trigger a new run.
    _setup_mock_connector(mock_server_client, admin_user)
    CCPairManager.run_once(
        cc_pair, from_beginning=False, user_performing_action=admin_user
    )

    time_before_second_attempt = datetime.now(timezone.utc)
    second_index_attempt = IndexAttemptManager.wait_for_index_attempt_start(
        cc_pair_id=cc_pair.id,
        index_attempts_to_ignore=[first_index_attempt.id],
        user_performing_action=admin_user,
    )
    IndexAttemptManager.wait_for_index_attempt_completion(
        index_attempt_id=second_index_attempt.id,
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )
    time_after_second_attempt = datetime.now(timezone.utc)

    # Fetch and validate the second attempt
    completed_second_attempt = IndexAttemptManager.get_index_attempt_by_id(
        index_attempt_id=second_index_attempt.id,
        cc_pair_id=cc_pair.id,
        user_performing_action=admin_user,
    )
    assert completed_second_attempt.status == IndexingStatus.SUCCESS
    assert completed_second_attempt.poll_range_start is not None
    assert completed_second_attempt.poll_range_end is not None

    # For the second run, poll_range_start should be the previous successful attempt's
    # poll_range_end minus the POLL_CONNECTOR_OFFSET
    expected_second_start = first_attempt_poll_end - timedelta(
        minutes=POLL_CONNECTOR_OFFSET
    )
    assert completed_second_attempt.poll_range_start == expected_second_start

    # `poll_range_end` should be sometime in between the time the attempt
    # started and the time it finished.
    # again, no way to have a more precise assertion here since the `poll_range_end`
    # can really be set anytime in that range and be "correct"
    assert (
        time_before_second_attempt
        <= completed_second_attempt.poll_range_end
        <= time_after_second_attempt
    )
