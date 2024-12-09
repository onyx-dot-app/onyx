import time
from collections.abc import Callable
from unittest.mock import MagicMock
from unittest.mock import patch

from danswer.connectors.google_drive.connector import GoogleDriveConnector
from danswer.connectors.models import Document
from tests.daily.connectors.google_drive.consts_and_utils import ADMIN_FOLDER_3_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import (
    assert_retrieved_docs_match_expected,
)
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_1_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_2_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_URL
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_3_URL
from tests.daily.connectors.google_drive.consts_and_utils import SHARED_DRIVE_1_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import TEST_USER_1_EMAIL
from tests.daily.connectors.google_drive.consts_and_utils import TEST_USER_1_FILE_IDS


@patch(
    "danswer.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_all(
    mock_get_api_key: MagicMock,
    google_drive_oauth_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    print("\n\nRunning test_all")
    connector = google_drive_oauth_connector_factory(
        primary_admin_email=TEST_USER_1_EMAIL,
        include_files_shared_with_me=True,
        include_shared_drives=True,
        include_my_drives=True,
        shared_folder_urls=None,
        shared_drive_urls=None,
        my_drive_emails=None,
    )
    retrieved_docs: list[Document] = []
    for doc_batch in connector.poll_source(0, time.time()):
        retrieved_docs.extend(doc_batch)

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
    assert_retrieved_docs_match_expected(
        retrieved_docs=retrieved_docs,
        expected_file_ids=expected_file_ids,
    )


@patch(
    "danswer.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_shared_drives_only(
    mock_get_api_key: MagicMock,
    google_drive_oauth_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    print("\n\nRunning test_shared_drives_only")
    connector = google_drive_oauth_connector_factory(
        primary_admin_email=TEST_USER_1_EMAIL,
        include_files_shared_with_me=False,
        include_shared_drives=True,
        include_my_drives=False,
        shared_folder_urls=None,
        shared_drive_urls=None,
        my_drive_emails=None,
    )
    retrieved_docs: list[Document] = []
    for doc_batch in connector.poll_source(0, time.time()):
        retrieved_docs.extend(doc_batch)

    expected_file_ids = (
        # These are the files from shared drives
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
    "danswer.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_shared_with_me_only(
    mock_get_api_key: MagicMock,
    google_drive_oauth_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    print("\n\nRunning test_shared_with_me_only")
    connector = google_drive_oauth_connector_factory(
        primary_admin_email=TEST_USER_1_EMAIL,
        include_files_shared_with_me=True,
        include_shared_drives=False,
        include_my_drives=False,
        shared_folder_urls=None,
        shared_drive_urls=None,
        my_drive_emails=None,
    )
    retrieved_docs: list[Document] = []
    for doc_batch in connector.poll_source(0, time.time()):
        retrieved_docs.extend(doc_batch)

    expected_file_ids = (
        # These are the files shared with me from admin
        ADMIN_FOLDER_3_FILE_IDS
        + list(range(0, 2))
    )
    assert_retrieved_docs_match_expected(
        retrieved_docs=retrieved_docs,
        expected_file_ids=expected_file_ids,
    )


@patch(
    "danswer.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_my_drive_only(
    mock_get_api_key: MagicMock,
    google_drive_oauth_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    print("\n\nRunning test_my_drive_only")
    connector = google_drive_oauth_connector_factory(
        primary_admin_email=TEST_USER_1_EMAIL,
        include_files_shared_with_me=False,
        include_shared_drives=False,
        include_my_drives=True,
        shared_folder_urls=None,
        shared_drive_urls=None,
        my_drive_emails=None,
    )
    retrieved_docs: list[Document] = []
    for doc_batch in connector.poll_source(0, time.time()):
        retrieved_docs.extend(doc_batch)

    # These are the files from my drive
    expected_file_ids = TEST_USER_1_FILE_IDS
    assert_retrieved_docs_match_expected(
        retrieved_docs=retrieved_docs,
        expected_file_ids=expected_file_ids,
    )


@patch(
    "danswer.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_shared_my_drive_folder(
    mock_get_api_key: MagicMock,
    google_drive_oauth_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    print("\n\nRunning test_shared_my_drive_folder")
    connector = google_drive_oauth_connector_factory(
        primary_admin_email=TEST_USER_1_EMAIL,
        include_files_shared_with_me=False,
        include_shared_drives=False,
        include_my_drives=True,
        shared_folder_urls=FOLDER_3_URL,
        shared_drive_urls=None,
        my_drive_emails=None,
    )
    retrieved_docs: list[Document] = []
    for doc_batch in connector.poll_source(0, time.time()):
        retrieved_docs.extend(doc_batch)

    expected_file_ids = (
        # this is a folder from admin's drive that is shared with me
        ADMIN_FOLDER_3_FILE_IDS
    )
    assert_retrieved_docs_match_expected(
        retrieved_docs=retrieved_docs,
        expected_file_ids=expected_file_ids,
    )


@patch(
    "danswer.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_shared_drive_folder(
    mock_get_api_key: MagicMock,
    google_drive_oauth_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    print("\n\nRunning test_shared_drive_folder")
    connector = google_drive_oauth_connector_factory(
        primary_admin_email=TEST_USER_1_EMAIL,
        include_files_shared_with_me=False,
        include_shared_drives=False,
        include_my_drives=True,
        shared_folder_urls=FOLDER_1_URL,
        shared_drive_urls=None,
        my_drive_emails=None,
    )
    retrieved_docs: list[Document] = []
    for doc_batch in connector.poll_source(0, time.time()):
        retrieved_docs.extend(doc_batch)

    expected_file_ids = FOLDER_1_FILE_IDS + FOLDER_1_1_FILE_IDS + FOLDER_1_2_FILE_IDS
    assert_retrieved_docs_match_expected(
        retrieved_docs=retrieved_docs,
        expected_file_ids=expected_file_ids,
    )
