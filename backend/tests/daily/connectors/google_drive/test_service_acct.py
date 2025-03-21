from collections.abc import Callable
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.connectors.google_drive.connector import GoogleDriveConnector
from tests.daily.connectors.google_drive.consts_and_utils import ADMIN_EMAIL
from tests.daily.connectors.google_drive.consts_and_utils import ADMIN_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import ADMIN_FOLDER_3_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import (
    assert_retrieved_docs_match_expected,
)
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_1_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_1_URL
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_2_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_2_URL
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_2_1_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_2_1_URL
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_2_2_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_2_2_URL
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_2_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_2_URL
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_3_URL
from tests.daily.connectors.google_drive.consts_and_utils import load_all_docs
from tests.daily.connectors.google_drive.consts_and_utils import SECTIONS_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import SHARED_DRIVE_1_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import SHARED_DRIVE_1_URL
from tests.daily.connectors.google_drive.consts_and_utils import SHARED_DRIVE_2_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import TEST_USER_1_EMAIL
from tests.daily.connectors.google_drive.consts_and_utils import TEST_USER_1_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import TEST_USER_2_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import TEST_USER_3_EMAIL
from tests.daily.connectors.google_drive.consts_and_utils import TEST_USER_3_FILE_IDS


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_include_all(
    mock_get_api_key: MagicMock,
    google_drive_service_acct_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    print("\n\nRunning test_include_all")
    connector = google_drive_service_acct_connector_factory(
        primary_admin_email=ADMIN_EMAIL,
        include_shared_drives=True,
        include_my_drives=True,
        include_files_shared_with_me=False,
        shared_folder_urls=None,
        shared_drive_urls=None,
        my_drive_emails=None,
    )
    retrieved_docs = load_all_docs(connector)

    # Should get everything
    expected_file_ids = (
        ADMIN_FILE_IDS
        + ADMIN_FOLDER_3_FILE_IDS
        + TEST_USER_1_FILE_IDS
        + TEST_USER_2_FILE_IDS
        + TEST_USER_3_FILE_IDS
        + SHARED_DRIVE_1_FILE_IDS
        + FOLDER_1_FILE_IDS
        + FOLDER_1_1_FILE_IDS
        + FOLDER_1_2_FILE_IDS
        + SHARED_DRIVE_2_FILE_IDS
        + FOLDER_2_FILE_IDS
        + FOLDER_2_1_FILE_IDS
        + FOLDER_2_2_FILE_IDS
        + SECTIONS_FILE_IDS
    )
    assert_retrieved_docs_match_expected(
        retrieved_docs=retrieved_docs,
        expected_file_ids=expected_file_ids,
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_include_shared_drives_only_with_size_threshold(
    mock_get_api_key: MagicMock,
    google_drive_service_acct_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    print("\n\nRunning test_include_shared_drives_only")
    connector = google_drive_service_acct_connector_factory(
        primary_admin_email=ADMIN_EMAIL,
        include_shared_drives=True,
        include_my_drives=False,
        include_files_shared_with_me=False,
        shared_folder_urls=None,
        shared_drive_urls=None,
        my_drive_emails=None,
    )

    # this threshold will skip one file
    connector.size_threshold = 16384

    retrieved_docs = load_all_docs(connector)

    assert len(retrieved_docs) == 50


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_include_shared_drives_only(
    mock_get_api_key: MagicMock,
    google_drive_service_acct_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    print("\n\nRunning test_include_shared_drives_only")
    connector = google_drive_service_acct_connector_factory(
        primary_admin_email=ADMIN_EMAIL,
        include_shared_drives=True,
        include_my_drives=False,
        include_files_shared_with_me=False,
        shared_folder_urls=None,
        shared_drive_urls=None,
        my_drive_emails=None,
    )

    retrieved_docs = load_all_docs(connector)

    # Should only get shared drives
    expected_file_ids = (
        SHARED_DRIVE_1_FILE_IDS
        + FOLDER_1_FILE_IDS
        + FOLDER_1_1_FILE_IDS
        + FOLDER_1_2_FILE_IDS
        + SHARED_DRIVE_2_FILE_IDS
        + FOLDER_2_FILE_IDS
        + FOLDER_2_1_FILE_IDS
        + FOLDER_2_2_FILE_IDS
        + SECTIONS_FILE_IDS
    )

    assert len(retrieved_docs) == 51

    assert_retrieved_docs_match_expected(
        retrieved_docs=retrieved_docs,
        expected_file_ids=expected_file_ids,
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_include_my_drives_only(
    mock_get_api_key: MagicMock,
    google_drive_service_acct_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    print("\n\nRunning test_include_my_drives_only")
    connector = google_drive_service_acct_connector_factory(
        primary_admin_email=ADMIN_EMAIL,
        include_shared_drives=False,
        include_my_drives=True,
        include_files_shared_with_me=False,
        shared_folder_urls=None,
        shared_drive_urls=None,
        my_drive_emails=None,
    )
    retrieved_docs = load_all_docs(connector)

    # Should only get everyone's My Drives
    expected_file_ids = (
        ADMIN_FILE_IDS
        + ADMIN_FOLDER_3_FILE_IDS
        + TEST_USER_1_FILE_IDS
        + TEST_USER_2_FILE_IDS
        + TEST_USER_3_FILE_IDS
    )
    assert_retrieved_docs_match_expected(
        retrieved_docs=retrieved_docs,
        expected_file_ids=expected_file_ids,
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_drive_one_only(
    mock_get_api_key: MagicMock,
    google_drive_service_acct_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    print("\n\nRunning test_drive_one_only")
    urls = [SHARED_DRIVE_1_URL]
    connector = google_drive_service_acct_connector_factory(
        primary_admin_email=ADMIN_EMAIL,
        include_shared_drives=False,
        include_my_drives=False,
        include_files_shared_with_me=False,
        shared_folder_urls=None,
        shared_drive_urls=",".join([str(url) for url in urls]),
        my_drive_emails=None,
    )
    retrieved_docs = load_all_docs(connector)

    # We ignore shared_drive_urls if include_shared_drives is False
    expected_file_ids = (
        SHARED_DRIVE_1_FILE_IDS
        + FOLDER_1_FILE_IDS
        + FOLDER_1_1_FILE_IDS
        + FOLDER_1_2_FILE_IDS
    )
    assert_retrieved_docs_match_expected(
        retrieved_docs=retrieved_docs,
        expected_file_ids=expected_file_ids,
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_folder_and_shared_drive(
    mock_get_api_key: MagicMock,
    google_drive_service_acct_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    print("\n\nRunning test_folder_and_shared_drive")
    drive_urls = [SHARED_DRIVE_1_URL]
    folder_urls = [FOLDER_2_URL]
    connector = google_drive_service_acct_connector_factory(
        primary_admin_email=ADMIN_EMAIL,
        include_shared_drives=False,
        include_my_drives=False,
        include_files_shared_with_me=False,
        shared_drive_urls=",".join([str(url) for url in drive_urls]),
        shared_folder_urls=",".join([str(url) for url in folder_urls]),
        my_drive_emails=None,
    )
    retrieved_docs = load_all_docs(connector)

    # Should get everything except for the top level files in drive 2
    expected_file_ids = (
        SHARED_DRIVE_1_FILE_IDS
        + FOLDER_1_FILE_IDS
        + FOLDER_1_1_FILE_IDS
        + FOLDER_1_2_FILE_IDS
        + FOLDER_2_FILE_IDS
        + FOLDER_2_1_FILE_IDS
        + FOLDER_2_2_FILE_IDS
    )
    assert_retrieved_docs_match_expected(
        retrieved_docs=retrieved_docs,
        expected_file_ids=expected_file_ids,
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_folders_only(
    mock_get_api_key: MagicMock,
    google_drive_service_acct_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    print("\n\nRunning test_folders_only")
    folder_urls = [
        FOLDER_1_2_URL,
        FOLDER_2_1_URL,
        FOLDER_2_2_URL,
        FOLDER_3_URL,
    ]
    # This should get converted to a drive request and spit out a warning in the logs
    shared_drive_urls = [
        FOLDER_1_1_URL,
    ]
    connector = google_drive_service_acct_connector_factory(
        primary_admin_email=ADMIN_EMAIL,
        include_shared_drives=False,
        include_my_drives=False,
        include_files_shared_with_me=False,
        shared_drive_urls=",".join([str(url) for url in shared_drive_urls]),
        shared_folder_urls=",".join([str(url) for url in folder_urls]),
        my_drive_emails=None,
    )
    retrieved_docs = load_all_docs(connector)

    expected_file_ids = (
        FOLDER_1_1_FILE_IDS
        + FOLDER_1_2_FILE_IDS
        + FOLDER_2_1_FILE_IDS
        + FOLDER_2_2_FILE_IDS
        + ADMIN_FOLDER_3_FILE_IDS
    )
    assert_retrieved_docs_match_expected(
        retrieved_docs=retrieved_docs,
        expected_file_ids=expected_file_ids,
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_specific_emails(
    mock_get_api_key: MagicMock,
    google_drive_service_acct_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    print("\n\nRunning test_specific_emails")
    my_drive_emails = [
        TEST_USER_1_EMAIL,
        TEST_USER_3_EMAIL,
    ]
    connector = google_drive_service_acct_connector_factory(
        primary_admin_email=ADMIN_EMAIL,
        include_shared_drives=False,
        include_my_drives=False,
        include_files_shared_with_me=False,
        shared_folder_urls=None,
        shared_drive_urls=None,
        my_drive_emails=",".join([str(email) for email in my_drive_emails]),
    )
    retrieved_docs = load_all_docs(connector)

    expected_file_ids = TEST_USER_1_FILE_IDS + TEST_USER_3_FILE_IDS
    assert_retrieved_docs_match_expected(
        retrieved_docs=retrieved_docs,
        expected_file_ids=expected_file_ids,
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def get_specific_folders_in_my_drive(
    mock_get_api_key: MagicMock,
    google_drive_service_acct_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    print("\n\nRunning get_specific_folders_in_my_drive")
    folder_urls = [
        FOLDER_3_URL,
    ]
    connector = google_drive_service_acct_connector_factory(
        primary_admin_email=ADMIN_EMAIL,
        include_shared_drives=False,
        include_my_drives=False,
        include_files_shared_with_me=False,
        shared_folder_urls=",".join([str(url) for url in folder_urls]),
        shared_drive_urls=None,
        my_drive_emails=None,
    )
    retrieved_docs = load_all_docs(connector)

    expected_file_ids = ADMIN_FOLDER_3_FILE_IDS
    assert_retrieved_docs_match_expected(
        retrieved_docs=retrieved_docs,
        expected_file_ids=expected_file_ids,
    )
