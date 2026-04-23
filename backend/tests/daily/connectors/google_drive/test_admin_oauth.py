from collections.abc import Callable
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.connectors.google_drive.connector import GoogleDriveConnector
from tests.daily.connectors.google_drive.consts_and_utils import _pick
from tests.daily.connectors.google_drive.consts_and_utils import ADMIN_EMAIL
from tests.daily.connectors.google_drive.consts_and_utils import ADMIN_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import ADMIN_FOLDER_3_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import ADMIN_MY_DRIVE_ID
from tests.daily.connectors.google_drive.consts_and_utils import (
    assert_expected_docs_in_retrieved_docs,
)
from tests.daily.connectors.google_drive.consts_and_utils import (
    assert_hierarchy_nodes_match_expected,
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
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_3_ID
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_3_URL
from tests.daily.connectors.google_drive.consts_and_utils import (
    get_expected_hierarchy_for_shared_drives,
)
from tests.daily.connectors.google_drive.consts_and_utils import load_connector_outputs
from tests.daily.connectors.google_drive.consts_and_utils import (
    PERM_SYNC_DRIVE_ADMIN_AND_USER_1_A_ID,
)
from tests.daily.connectors.google_drive.consts_and_utils import (
    PERM_SYNC_DRIVE_ADMIN_AND_USER_1_B_ID,
)
from tests.daily.connectors.google_drive.consts_and_utils import (
    PERM_SYNC_DRIVE_ADMIN_ONLY_ID,
)
from tests.daily.connectors.google_drive.consts_and_utils import PILL_FOLDER_ID
from tests.daily.connectors.google_drive.consts_and_utils import (
    RESTRICTED_ACCESS_FOLDER_ID,
)
from tests.daily.connectors.google_drive.consts_and_utils import SECTIONS_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import SECTIONS_FOLDER_ID
from tests.daily.connectors.google_drive.consts_and_utils import SHARED_DRIVE_1_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import SHARED_DRIVE_1_URL
from tests.daily.connectors.google_drive.consts_and_utils import SHARED_DRIVE_2_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import (
    TEST_USER_1_EXTRA_DRIVE_1_ID,
)
from tests.daily.connectors.google_drive.consts_and_utils import (
    TEST_USER_1_EXTRA_DRIVE_2_ID,
)
from tests.daily.connectors.google_drive.consts_and_utils import (
    TEST_USER_1_EXTRA_FOLDER_ID,
)


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_include_all(
    mock_get_api_key: MagicMock,  # noqa: ARG001
    google_drive_oauth_uploaded_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    print("\n\nRunning test_include_all")
    connector = google_drive_oauth_uploaded_connector_factory(
        primary_admin_email=ADMIN_EMAIL,
        include_shared_drives=True,
        include_my_drives=True,
        include_files_shared_with_me=False,
        shared_folder_urls=None,
        my_drive_emails=None,
        shared_drive_urls=None,
    )
    output = load_connector_outputs(connector)

    expected_file_ids = (
        ADMIN_FILE_IDS
        + ADMIN_FOLDER_3_FILE_IDS
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
        retrieved_docs=output.documents,
        expected_file_ids=expected_file_ids,
    )

    expected_nodes = get_expected_hierarchy_for_shared_drives(
        include_drive_1=True,
        include_drive_2=True,
        include_restricted_folder=False,
    )
    expected_nodes.update(
        _pick(
            PERM_SYNC_DRIVE_ADMIN_ONLY_ID,
            PERM_SYNC_DRIVE_ADMIN_AND_USER_1_A_ID,
            PERM_SYNC_DRIVE_ADMIN_AND_USER_1_B_ID,
            TEST_USER_1_EXTRA_DRIVE_1_ID,
            TEST_USER_1_EXTRA_DRIVE_2_ID,
            ADMIN_MY_DRIVE_ID,
            PILL_FOLDER_ID,
            RESTRICTED_ACCESS_FOLDER_ID,
            TEST_USER_1_EXTRA_FOLDER_ID,
            FOLDER_3_ID,
        )
    )
    assert_hierarchy_nodes_match_expected(
        retrieved_nodes=output.hierarchy_nodes,
        expected_nodes=expected_nodes,
        ignorable_node_ids={RESTRICTED_ACCESS_FOLDER_ID},
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_include_shared_drives_only(
    mock_get_api_key: MagicMock,  # noqa: ARG001
    google_drive_oauth_uploaded_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    print("\n\nRunning test_include_shared_drives_only")
    connector = google_drive_oauth_uploaded_connector_factory(
        primary_admin_email=ADMIN_EMAIL,
        include_shared_drives=True,
        include_my_drives=False,
        include_files_shared_with_me=False,
        shared_folder_urls=None,
        my_drive_emails=None,
        shared_drive_urls=None,
    )
    output = load_connector_outputs(connector)

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
    assert_expected_docs_in_retrieved_docs(
        retrieved_docs=output.documents,
        expected_file_ids=expected_file_ids,
    )

    expected_nodes = get_expected_hierarchy_for_shared_drives(
        include_drive_1=True,
        include_drive_2=True,
        include_restricted_folder=False,
    )
    expected_nodes.update(
        _pick(
            PERM_SYNC_DRIVE_ADMIN_ONLY_ID,
            PERM_SYNC_DRIVE_ADMIN_AND_USER_1_A_ID,
            PERM_SYNC_DRIVE_ADMIN_AND_USER_1_B_ID,
            TEST_USER_1_EXTRA_DRIVE_1_ID,
            TEST_USER_1_EXTRA_DRIVE_2_ID,
            RESTRICTED_ACCESS_FOLDER_ID,
        )
    )
    assert_hierarchy_nodes_match_expected(
        retrieved_nodes=output.hierarchy_nodes,
        expected_nodes=expected_nodes,
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_include_my_drives_only(
    mock_get_api_key: MagicMock,  # noqa: ARG001
    google_drive_oauth_uploaded_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    print("\n\nRunning test_include_my_drives_only")
    connector = google_drive_oauth_uploaded_connector_factory(
        primary_admin_email=ADMIN_EMAIL,
        include_shared_drives=False,
        include_my_drives=True,
        include_files_shared_with_me=False,
        shared_folder_urls=None,
        my_drive_emails=None,
        shared_drive_urls=None,
    )
    output = load_connector_outputs(connector)

    expected_file_ids = ADMIN_FILE_IDS + ADMIN_FOLDER_3_FILE_IDS
    assert_expected_docs_in_retrieved_docs(
        retrieved_docs=output.documents,
        expected_file_ids=expected_file_ids,
    )

    expected_nodes = _pick(
        FOLDER_3_ID,
        ADMIN_MY_DRIVE_ID,
        PILL_FOLDER_ID,
        TEST_USER_1_EXTRA_FOLDER_ID,
    )
    assert_hierarchy_nodes_match_expected(
        retrieved_nodes=output.hierarchy_nodes,
        expected_nodes=expected_nodes,
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_drive_one_only(
    mock_get_api_key: MagicMock,  # noqa: ARG001
    google_drive_oauth_uploaded_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    print("\n\nRunning test_drive_one_only")
    drive_urls = [SHARED_DRIVE_1_URL]
    connector = google_drive_oauth_uploaded_connector_factory(
        primary_admin_email=ADMIN_EMAIL,
        include_shared_drives=True,
        include_my_drives=False,
        include_files_shared_with_me=False,
        shared_folder_urls=None,
        my_drive_emails=None,
        shared_drive_urls=",".join([str(url) for url in drive_urls]),
    )
    output = load_connector_outputs(connector)

    expected_file_ids = (
        SHARED_DRIVE_1_FILE_IDS
        + FOLDER_1_FILE_IDS
        + FOLDER_1_1_FILE_IDS
        + FOLDER_1_2_FILE_IDS
    )
    assert_expected_docs_in_retrieved_docs(
        retrieved_docs=output.documents,
        expected_file_ids=expected_file_ids,
    )

    expected_nodes = get_expected_hierarchy_for_shared_drives(
        include_drive_1=True,
        include_drive_2=False,
        include_restricted_folder=False,
    )
    assert_hierarchy_nodes_match_expected(
        retrieved_nodes=output.hierarchy_nodes,
        expected_nodes=expected_nodes,
        ignorable_node_ids={RESTRICTED_ACCESS_FOLDER_ID},
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_folder_and_shared_drive(
    mock_get_api_key: MagicMock,  # noqa: ARG001
    google_drive_oauth_uploaded_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    print("\n\nRunning test_folder_and_shared_drive")
    drive_urls = [SHARED_DRIVE_1_URL]
    folder_urls = [FOLDER_2_URL]
    connector = google_drive_oauth_uploaded_connector_factory(
        primary_admin_email=ADMIN_EMAIL,
        include_shared_drives=True,
        include_my_drives=False,
        include_files_shared_with_me=False,
        shared_folder_urls=",".join([str(url) for url in folder_urls]),
        my_drive_emails=None,
        shared_drive_urls=",".join([str(url) for url in drive_urls]),
    )
    output = load_connector_outputs(connector)

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
        retrieved_docs=output.documents,
        expected_file_ids=expected_file_ids,
    )

    expected_nodes = get_expected_hierarchy_for_shared_drives(
        include_drive_1=True,
        include_drive_2=True,
        include_restricted_folder=False,
    )
    expected_nodes.pop(SECTIONS_FOLDER_ID, None)
    assert_hierarchy_nodes_match_expected(
        retrieved_nodes=output.hierarchy_nodes,
        expected_nodes=expected_nodes,
        ignorable_node_ids={RESTRICTED_ACCESS_FOLDER_ID},
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_folders_only(
    mock_get_api_key: MagicMock,  # noqa: ARG001
    google_drive_oauth_uploaded_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    print("\n\nRunning test_folders_only")
    folder_urls = [
        FOLDER_1_2_URL,
        FOLDER_2_1_URL,
        FOLDER_2_2_URL,
        FOLDER_3_URL,
    ]
    shared_drive_urls = [
        FOLDER_1_1_URL,
    ]
    connector = google_drive_oauth_uploaded_connector_factory(
        primary_admin_email=ADMIN_EMAIL,
        include_shared_drives=True,
        include_my_drives=False,
        include_files_shared_with_me=False,
        shared_folder_urls=",".join([str(url) for url in folder_urls]),
        my_drive_emails=None,
        shared_drive_urls=",".join([str(url) for url in shared_drive_urls]),
    )
    output = load_connector_outputs(connector)

    expected_file_ids = (
        FOLDER_1_1_FILE_IDS
        + FOLDER_1_2_FILE_IDS
        + FOLDER_2_1_FILE_IDS
        + FOLDER_2_2_FILE_IDS
        + ADMIN_FOLDER_3_FILE_IDS
    )
    assert_expected_docs_in_retrieved_docs(
        retrieved_docs=output.documents,
        expected_file_ids=expected_file_ids,
    )

    expected_nodes = get_expected_hierarchy_for_shared_drives(
        include_drive_1=True,
        include_drive_2=True,
        include_restricted_folder=False,
    )
    expected_nodes.pop(SECTIONS_FOLDER_ID, None)
    expected_nodes.update(_pick(ADMIN_MY_DRIVE_ID, FOLDER_3_ID))
    assert_hierarchy_nodes_match_expected(
        retrieved_nodes=output.hierarchy_nodes,
        expected_nodes=expected_nodes,
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_personal_folders_only(
    mock_get_api_key: MagicMock,  # noqa: ARG001
    google_drive_oauth_uploaded_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    print("\n\nRunning test_personal_folders_only")
    folder_urls = [
        FOLDER_3_URL,
    ]
    connector = google_drive_oauth_uploaded_connector_factory(
        primary_admin_email=ADMIN_EMAIL,
        include_shared_drives=True,
        include_my_drives=False,
        include_files_shared_with_me=False,
        shared_folder_urls=",".join([str(url) for url in folder_urls]),
        my_drive_emails=None,
        shared_drive_urls=None,
    )
    output = load_connector_outputs(connector)

    expected_file_ids = ADMIN_FOLDER_3_FILE_IDS
    assert_expected_docs_in_retrieved_docs(
        retrieved_docs=output.documents,
        expected_file_ids=expected_file_ids,
    )

    expected_nodes = _pick(FOLDER_3_ID, ADMIN_MY_DRIVE_ID)
    assert_hierarchy_nodes_match_expected(
        retrieved_nodes=output.hierarchy_nodes,
        expected_nodes=expected_nodes,
    )
