from collections.abc import Callable
from unittest.mock import MagicMock
from unittest.mock import patch
from urllib.parse import urlparse

from onyx.connectors.google_drive.connector import GoogleDriveConnector
from tests.daily.connectors.google_drive.consts_and_utils import ADMIN_EMAIL
from tests.daily.connectors.google_drive.consts_and_utils import ADMIN_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import ADMIN_FOLDER_3_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import (
    assert_expected_docs_in_retrieved_docs,
)
from tests.daily.connectors.google_drive.consts_and_utils import (
    EXTERNAL_SHARED_DOC_SINGLETON,
)
from tests.daily.connectors.google_drive.consts_and_utils import (
    EXTERNAL_SHARED_DOCS_IN_FOLDER,
)
from tests.daily.connectors.google_drive.consts_and_utils import (
    EXTERNAL_SHARED_FOLDER_URL,
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
from tests.daily.connectors.google_drive.consts_and_utils import id_to_name
from tests.daily.connectors.google_drive.consts_and_utils import load_all_docs
from tests.daily.connectors.google_drive.consts_and_utils import (
    MISC_SHARED_DRIVE_FNAMES,
)
from tests.daily.connectors.google_drive.consts_and_utils import (
    RESTRICTED_ACCESS_FOLDER_URL,
)
from tests.daily.connectors.google_drive.consts_and_utils import SECTIONS_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import SHARED_DRIVE_1_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import SHARED_DRIVE_1_URL
from tests.daily.connectors.google_drive.consts_and_utils import SHARED_DRIVE_2_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import TEST_USER_1_EMAIL
from tests.daily.connectors.google_drive.consts_and_utils import TEST_USER_1_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import TEST_USER_2_EMAIL
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
    assert_expected_docs_in_retrieved_docs(
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
    print("\n\nRunning test_include_shared_drives_only_with_size_threshold")
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

    expected_file_names = {id_to_name(file_id) for file_id in expected_file_ids}
    expected_file_names.update(MISC_SHARED_DRIVE_FNAMES)
    retrieved_file_names = {doc.semantic_identifier for doc in retrieved_docs}
    for name in expected_file_names - retrieved_file_names:
        print(f"expected but did not retrieve: {name}")
    for name in retrieved_file_names - expected_file_names:
        print(f"retrieved but did not expect: {name}")

    # 2 extra files from shared drive owned by non-admin and not shared with admin
    # TODO: added a file in a "restricted" folder, which the connector sometimes succeeds at finding
    # and adding. Specifically, our shared drive retrieval logic currently assumes that
    # "having access to a shared drive" means that the connector has access to all files in the shared drive.
    # therefore when a user successfully retrieves a shared drive, we mark it as "done". If that user's
    # access is restricted for a folder in the shared drive, the connector will not retrieve that folder.
    # If instead someone with FULL access to the shared drive retrieves it, the connector will retrieve
    # the folder and all its files. There is currently no consistency to the order of assignment of users
    # to shared drives, so this is a heisenbug. When we guarantee that restricted folders are retrieved,
    # we can change this to 52
    assert len(retrieved_docs) == 50 or len(retrieved_docs) == 51


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

    # 2 extra files from shared drive owned by non-admin and not shared with admin
    # TODO: switch to 54 when restricted access issue is resolved
    assert len(retrieved_docs) == 52 or len(retrieved_docs) == 53

    assert_expected_docs_in_retrieved_docs(
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
    assert_expected_docs_in_retrieved_docs(
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
    assert_expected_docs_in_retrieved_docs(
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
    assert_expected_docs_in_retrieved_docs(
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
    assert_expected_docs_in_retrieved_docs(
        retrieved_docs=retrieved_docs,
        expected_file_ids=expected_file_ids,
    )


def test_shared_folder_owned_by_external_user(
    google_drive_service_acct_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    print("\n\nRunning test_shared_folder_owned_by_external_user")
    connector = google_drive_service_acct_connector_factory(
        primary_admin_email=ADMIN_EMAIL,
        include_shared_drives=False,
        include_my_drives=False,
        include_files_shared_with_me=False,
        shared_drive_urls=None,
        shared_folder_urls=EXTERNAL_SHARED_FOLDER_URL,
        my_drive_emails=None,
    )
    retrieved_docs = load_all_docs(connector)

    expected_docs = EXTERNAL_SHARED_DOCS_IN_FOLDER

    assert len(retrieved_docs) == len(expected_docs)  # 1 for now
    assert expected_docs[0] in retrieved_docs[0].id


def test_shared_with_me(
    google_drive_service_acct_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    print("\n\nRunning test_shared_with_me")
    connector = google_drive_service_acct_connector_factory(
        primary_admin_email=ADMIN_EMAIL,
        include_shared_drives=False,
        include_my_drives=True,
        include_files_shared_with_me=True,
        shared_drive_urls=None,
        shared_folder_urls=None,
        my_drive_emails=None,
    )
    retrieved_docs = load_all_docs(connector)

    print(retrieved_docs)

    expected_file_ids = (
        ADMIN_FILE_IDS
        + ADMIN_FOLDER_3_FILE_IDS
        + TEST_USER_1_FILE_IDS
        + TEST_USER_2_FILE_IDS
        + TEST_USER_3_FILE_IDS
    )
    assert_expected_docs_in_retrieved_docs(
        retrieved_docs=retrieved_docs,
        expected_file_ids=expected_file_ids,
    )

    retrieved_ids = {urlparse(doc.id).path.split("/")[-1] for doc in retrieved_docs}
    for id in retrieved_ids:
        print(id)

    assert EXTERNAL_SHARED_DOC_SINGLETON.split("/")[-1] in retrieved_ids
    assert EXTERNAL_SHARED_DOCS_IN_FOLDER[0].split("/")[-1] in retrieved_ids


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
    assert_expected_docs_in_retrieved_docs(
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
    assert_expected_docs_in_retrieved_docs(
        retrieved_docs=retrieved_docs,
        expected_file_ids=expected_file_ids,
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_specific_user_emails_restricted_folder(
    mock_get_api_key: MagicMock,
    google_drive_service_acct_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    print("\n\nRunning test_specific_user_emails_restricted_folder")

    # Test with admin email - should get 1 doc
    admin_connector = google_drive_service_acct_connector_factory(
        primary_admin_email=ADMIN_EMAIL,
        include_shared_drives=False,
        include_my_drives=False,
        include_files_shared_with_me=False,
        shared_folder_urls=RESTRICTED_ACCESS_FOLDER_URL,
        shared_drive_urls=None,
        my_drive_emails=None,
        specific_user_emails=ADMIN_EMAIL,
    )
    admin_docs = load_all_docs(admin_connector)
    assert len(admin_docs) == 1

    # Test with test users - should get 0 docs
    test_users = [TEST_USER_1_EMAIL, TEST_USER_2_EMAIL, TEST_USER_3_EMAIL]
    test_connector = google_drive_service_acct_connector_factory(
        primary_admin_email=ADMIN_EMAIL,
        include_shared_drives=False,
        include_my_drives=False,
        include_files_shared_with_me=False,
        shared_folder_urls=RESTRICTED_ACCESS_FOLDER_URL,
        shared_drive_urls=None,
        my_drive_emails=None,
        specific_user_emails=",".join(test_users),
    )
    test_docs = load_all_docs(test_connector)
    assert len(test_docs) == 0


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_specific_user_email_shared_with_me(
    mock_get_api_key: MagicMock,
    google_drive_service_acct_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    print("\n\nRunning test_specific_user_email_shared_with_me")

    # Test with admin email - should get 1 doc
    connector = google_drive_service_acct_connector_factory(
        primary_admin_email=ADMIN_EMAIL,
        include_shared_drives=False,
        include_my_drives=True,
        include_files_shared_with_me=False,  # This is what is set in the UI unfortunately
        shared_folder_urls=None,
        shared_drive_urls=None,
        my_drive_emails=None,
        specific_user_emails=TEST_USER_1_EMAIL,
    )
    docs = load_all_docs(connector)
    expected = [id_to_name(file_id) for file_id in TEST_USER_1_FILE_IDS]
    expected += ["private_file", "shared_file"]  # in My Drive
    expected += ["read only users can't download"]  # Shared with me

    expected += [id_to_name(file_id) for file_id in [0, 1] + ADMIN_FOLDER_3_FILE_IDS]

    # these are in shared drives
    # expected += ['perm_sync_doc_0ACOrCU1EMD1hUk9PVA_ab63b976-effb-49af-84e7-423d17a17dd7']
    # expected += ['file_22.txt'] # Shared drive

    doc_titles = set(doc.semantic_identifier for doc in docs)
    assert doc_titles == set(expected)
