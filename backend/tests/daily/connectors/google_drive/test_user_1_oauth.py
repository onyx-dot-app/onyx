from collections.abc import Callable
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.models import Document
from tests.daily.connectors.google_drive.consts_and_utils import _clear_parents
from tests.daily.connectors.google_drive.consts_and_utils import _pick
from tests.daily.connectors.google_drive.consts_and_utils import ADMIN_FOLDER_3_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import (
    assert_expected_docs_in_retrieved_docs,
)
from tests.daily.connectors.google_drive.consts_and_utils import (
    assert_hierarchy_nodes_match_expected,
)
from tests.daily.connectors.google_drive.consts_and_utils import (
    DONWLOAD_REVOKED_FILE_ID,
)
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_1_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_1_ID
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_2_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_2_ID
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_ID
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_URL
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_3_ID
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_3_URL
from tests.daily.connectors.google_drive.consts_and_utils import (
    get_expected_hierarchy_for_test_user_1,
)
from tests.daily.connectors.google_drive.consts_and_utils import (
    get_expected_hierarchy_for_test_user_1_my_drive_only,
)
from tests.daily.connectors.google_drive.consts_and_utils import (
    get_expected_hierarchy_for_test_user_1_shared_drives_only,
)
from tests.daily.connectors.google_drive.consts_and_utils import (
    get_expected_hierarchy_for_test_user_1_shared_with_me_only,
)
from tests.daily.connectors.google_drive.consts_and_utils import load_connector_outputs
from tests.daily.connectors.google_drive.consts_and_utils import SHARED_DRIVE_1_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import SHARED_DRIVE_1_ID
from tests.daily.connectors.google_drive.consts_and_utils import TEST_USER_1_EMAIL
from tests.daily.connectors.google_drive.consts_and_utils import TEST_USER_1_FILE_IDS
from tests.daily.connectors.utils import ConnectorOutput


def _check_for_error(
    output: ConnectorOutput,
    expected_file_ids: list[int],
) -> list[Document]:
    retrieved_docs = output.documents
    retrieved_failures = output.failures
    assert len(retrieved_failures) <= 1

    if len(retrieved_failures) == 1:
        fail_msg = retrieved_failures[0].failure_message
        assert "HttpError 403" in fail_msg
        assert f"file_{DONWLOAD_REVOKED_FILE_ID}.txt" in fail_msg

    expected_file_ids.remove(DONWLOAD_REVOKED_FILE_ID)
    return retrieved_docs


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_all(
    mock_get_api_key: MagicMock,  # noqa: ARG001
    google_drive_oauth_uploaded_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    print("\n\nRunning test_all")
    connector = google_drive_oauth_uploaded_connector_factory(
        primary_admin_email=TEST_USER_1_EMAIL,
        include_files_shared_with_me=True,
        include_shared_drives=True,
        include_my_drives=True,
        shared_folder_urls=None,
        shared_drive_urls=None,
        my_drive_emails=None,
    )
    output = load_connector_outputs(connector)

    expected_file_ids = (
        TEST_USER_1_FILE_IDS
        + SHARED_DRIVE_1_FILE_IDS
        + FOLDER_1_FILE_IDS
        + FOLDER_1_1_FILE_IDS
        + FOLDER_1_2_FILE_IDS
        + ADMIN_FOLDER_3_FILE_IDS
        + list(range(0, 2))
    )

    retrieved_docs = _check_for_error(output, expected_file_ids)

    assert_expected_docs_in_retrieved_docs(
        retrieved_docs=retrieved_docs,
        expected_file_ids=expected_file_ids,
    )

    assert_hierarchy_nodes_match_expected(
        retrieved_nodes=output.hierarchy_nodes,
        expected_nodes=get_expected_hierarchy_for_test_user_1(),
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_shared_drives_only(
    mock_get_api_key: MagicMock,  # noqa: ARG001
    google_drive_oauth_uploaded_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    print("\n\nRunning test_shared_drives_only")
    connector = google_drive_oauth_uploaded_connector_factory(
        primary_admin_email=TEST_USER_1_EMAIL,
        include_files_shared_with_me=False,
        include_shared_drives=True,
        include_my_drives=False,
        shared_folder_urls=None,
        shared_drive_urls=None,
        my_drive_emails=None,
    )
    output = load_connector_outputs(connector)

    expected_file_ids = (
        SHARED_DRIVE_1_FILE_IDS
        + FOLDER_1_FILE_IDS
        + FOLDER_1_1_FILE_IDS
        + FOLDER_1_2_FILE_IDS
    )

    retrieved_docs = _check_for_error(output, expected_file_ids)
    assert_expected_docs_in_retrieved_docs(
        retrieved_docs=retrieved_docs,
        expected_file_ids=expected_file_ids,
    )

    assert_hierarchy_nodes_match_expected(
        retrieved_nodes=output.hierarchy_nodes,
        expected_nodes=get_expected_hierarchy_for_test_user_1_shared_drives_only(),
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_shared_with_me_only(
    mock_get_api_key: MagicMock,  # noqa: ARG001
    google_drive_oauth_uploaded_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    print("\n\nRunning test_shared_with_me_only")
    connector = google_drive_oauth_uploaded_connector_factory(
        primary_admin_email=TEST_USER_1_EMAIL,
        include_files_shared_with_me=True,
        include_shared_drives=False,
        include_my_drives=False,
        shared_folder_urls=None,
        shared_drive_urls=None,
        my_drive_emails=None,
    )
    output = load_connector_outputs(connector)

    expected_file_ids = ADMIN_FOLDER_3_FILE_IDS + list(range(0, 2))
    assert_expected_docs_in_retrieved_docs(
        retrieved_docs=output.documents,
        expected_file_ids=expected_file_ids,
    )

    assert_hierarchy_nodes_match_expected(
        retrieved_nodes=output.hierarchy_nodes,
        expected_nodes=get_expected_hierarchy_for_test_user_1_shared_with_me_only(),
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_my_drive_only(
    mock_get_api_key: MagicMock,  # noqa: ARG001
    google_drive_oauth_uploaded_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    print("\n\nRunning test_my_drive_only")
    connector = google_drive_oauth_uploaded_connector_factory(
        primary_admin_email=TEST_USER_1_EMAIL,
        include_files_shared_with_me=False,
        include_shared_drives=False,
        include_my_drives=True,
        shared_folder_urls=None,
        shared_drive_urls=None,
        my_drive_emails=None,
    )
    output = load_connector_outputs(connector)

    expected_file_ids = TEST_USER_1_FILE_IDS
    assert_expected_docs_in_retrieved_docs(
        retrieved_docs=output.documents,
        expected_file_ids=expected_file_ids,
    )

    assert_hierarchy_nodes_match_expected(
        retrieved_nodes=output.hierarchy_nodes,
        expected_nodes=get_expected_hierarchy_for_test_user_1_my_drive_only(),
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_shared_my_drive_folder(
    mock_get_api_key: MagicMock,  # noqa: ARG001
    google_drive_oauth_uploaded_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    print("\n\nRunning test_shared_my_drive_folder")
    connector = google_drive_oauth_uploaded_connector_factory(
        primary_admin_email=TEST_USER_1_EMAIL,
        include_files_shared_with_me=False,
        include_shared_drives=False,
        include_my_drives=True,
        shared_folder_urls=FOLDER_3_URL,
        shared_drive_urls=None,
        my_drive_emails=None,
    )
    output = load_connector_outputs(connector)

    expected_file_ids = ADMIN_FOLDER_3_FILE_IDS
    assert_expected_docs_in_retrieved_docs(
        retrieved_docs=output.documents,
        expected_file_ids=expected_file_ids,
    )

    assert_hierarchy_nodes_match_expected(
        retrieved_nodes=output.hierarchy_nodes,
        expected_nodes=_clear_parents(_pick(FOLDER_3_ID), FOLDER_3_ID),
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_shared_drive_folder(
    mock_get_api_key: MagicMock,  # noqa: ARG001
    google_drive_oauth_uploaded_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    print("\n\nRunning test_shared_drive_folder")
    connector = google_drive_oauth_uploaded_connector_factory(
        primary_admin_email=TEST_USER_1_EMAIL,
        include_files_shared_with_me=False,
        include_shared_drives=False,
        include_my_drives=True,
        shared_folder_urls=FOLDER_1_URL,
        shared_drive_urls=None,
        my_drive_emails=None,
    )
    output = load_connector_outputs(connector)

    expected_file_ids = FOLDER_1_FILE_IDS + FOLDER_1_1_FILE_IDS + FOLDER_1_2_FILE_IDS
    assert_expected_docs_in_retrieved_docs(
        retrieved_docs=output.documents,
        expected_file_ids=expected_file_ids,
    )

    assert_hierarchy_nodes_match_expected(
        retrieved_nodes=output.hierarchy_nodes,
        expected_nodes=_pick(
            SHARED_DRIVE_1_ID, FOLDER_1_ID, FOLDER_1_1_ID, FOLDER_1_2_ID
        ),
    )
