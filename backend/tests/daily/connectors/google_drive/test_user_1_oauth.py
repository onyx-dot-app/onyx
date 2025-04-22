from collections.abc import Callable
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from tests.daily.connectors.google_drive.consts_and_utils import ADMIN_FOLDER_3_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import (
    assert_expected_docs_in_retrieved_docs,
)
from tests.daily.connectors.google_drive.consts_and_utils import (
    DONWLOAD_REVOKED_FILE_ID,
)
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_1_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_2_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_URL
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_3_URL
from tests.daily.connectors.google_drive.consts_and_utils import load_all_docs
from tests.daily.connectors.google_drive.consts_and_utils import (
    load_all_docs_with_failures,
)
from tests.daily.connectors.google_drive.consts_and_utils import SHARED_DRIVE_1_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import TEST_USER_1_EMAIL
from tests.daily.connectors.google_drive.consts_and_utils import TEST_USER_1_FILE_IDS


def _check_for_error(
    retrieved_docs_failures: list[Document | ConnectorFailure],
    expected_file_ids: list[int],
) -> list[Document]:
    retrieved_docs = [
        doc for doc in retrieved_docs_failures if isinstance(doc, Document)
    ]
    retrieved_failures = [
        failure
        for failure in retrieved_docs_failures
        if isinstance(failure, ConnectorFailure)
    ]
    assert len(retrieved_failures) <= 1

    # current behavior is to fail silently for 403s; leaving this here for when we revert
    # if all 403s get fixed
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
    mock_get_api_key: MagicMock,
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
    retrieved_docs_failures = load_all_docs_with_failures(connector)

    expected_file_ids = (
        # These are the files from my drive
        TEST_USER_1_FILE_IDS
        # These are the files from shared drives
        + SHARED_DRIVE_1_FILE_IDS
        + FOLDER_1_FILE_IDS
        + FOLDER_1_1_FILE_IDS
        + FOLDER_1_2_FILE_IDS
        # These are the files shared with me from admin
        + ADMIN_FOLDER_3_FILE_IDS
        + list(range(0, 2))
    )

    retrieved_docs = _check_for_error(retrieved_docs_failures, expected_file_ids)

    assert_expected_docs_in_retrieved_docs(
        retrieved_docs=retrieved_docs,
        expected_file_ids=expected_file_ids,
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_shared_drives_only(
    mock_get_api_key: MagicMock,
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
    retrieved_docs_failures = load_all_docs_with_failures(connector)

    expected_file_ids = (
        # These are the files from shared drives
        SHARED_DRIVE_1_FILE_IDS
        + FOLDER_1_FILE_IDS
        + FOLDER_1_1_FILE_IDS
        + FOLDER_1_2_FILE_IDS
    )

    retrieved_docs = _check_for_error(retrieved_docs_failures, expected_file_ids)
    assert_expected_docs_in_retrieved_docs(
        retrieved_docs=retrieved_docs,
        expected_file_ids=expected_file_ids,
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_shared_with_me_only(
    mock_get_api_key: MagicMock,
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
    retrieved_docs = load_all_docs(connector)

    expected_file_ids = (
        # These are the files shared with me from admin
        ADMIN_FOLDER_3_FILE_IDS
        + list(range(0, 2))
    )
    assert_expected_docs_in_retrieved_docs(
        retrieved_docs=retrieved_docs,
        expected_file_ids=expected_file_ids,
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_my_drive_only(
    mock_get_api_key: MagicMock,
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
    retrieved_docs = load_all_docs(connector)

    # These are the files from my drive
    expected_file_ids = TEST_USER_1_FILE_IDS
    assert_expected_docs_in_retrieved_docs(
        retrieved_docs=retrieved_docs,
        expected_file_ids=expected_file_ids,
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_shared_my_drive_folder(
    mock_get_api_key: MagicMock,
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
    retrieved_docs = load_all_docs(connector)

    expected_file_ids = (
        # this is a folder from admin's drive that is shared with me
        ADMIN_FOLDER_3_FILE_IDS
    )
    assert_expected_docs_in_retrieved_docs(
        retrieved_docs=retrieved_docs,
        expected_file_ids=expected_file_ids,
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_shared_drive_folder(
    mock_get_api_key: MagicMock,
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
    retrieved_docs = load_all_docs(connector)

    expected_file_ids = FOLDER_1_FILE_IDS + FOLDER_1_1_FILE_IDS + FOLDER_1_2_FILE_IDS
    assert_expected_docs_in_retrieved_docs(
        retrieved_docs=retrieved_docs,
        expected_file_ids=expected_file_ids,
    )
