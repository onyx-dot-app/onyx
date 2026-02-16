from collections.abc import Callable
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.connectors.google_drive.connector import GoogleDriveConnector
from tests.daily.connectors.google_drive.consts_and_utils import ADMIN_EMAIL
from tests.daily.connectors.google_drive.consts_and_utils import ADMIN_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import ADMIN_FOLDER_3_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import (
    ADMIN_MY_DRIVE_ID,
)
from tests.daily.connectors.google_drive.consts_and_utils import (
    assert_expected_docs_in_retrieved_docs,
)
from tests.daily.connectors.google_drive.consts_and_utils import (
    assert_hierarchy_nodes_match_expected,
)
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_1_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_1_ID
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_1_URL
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_2_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_2_ID
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_2_URL
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_ID
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_2_1_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_2_1_ID
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_2_1_URL
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_2_2_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_2_2_ID
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_2_2_URL
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_2_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_2_ID
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
from tests.daily.connectors.google_drive.consts_and_utils import (
    PILL_FOLDER_ID,
)
from tests.daily.connectors.google_drive.consts_and_utils import (
    RESTRICTED_ACCESS_FOLDER_ID,
)
from tests.daily.connectors.google_drive.consts_and_utils import SECTIONS_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import SHARED_DRIVE_1_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import SHARED_DRIVE_1_ID
from tests.daily.connectors.google_drive.consts_and_utils import SHARED_DRIVE_1_URL
from tests.daily.connectors.google_drive.consts_and_utils import SHARED_DRIVE_2_FILE_IDS
from tests.daily.connectors.google_drive.consts_and_utils import SHARED_DRIVE_2_ID
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

    # Should get everything in shared and admin's My Drive with oauth
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

    # Verify hierarchy nodes for shared drives
    # When include_shared_drives=True, we get ALL shared drives the admin has access to
    expected_ids, expected_parents = get_expected_hierarchy_for_shared_drives(
        include_drive_1=True,
        include_drive_2=True,
        # Restricted folder may not always be retrieved due to access limitations
        include_restricted_folder=False,
    )

    # Add additional shared drives that admin has access to
    expected_ids.add(PERM_SYNC_DRIVE_ADMIN_ONLY_ID)
    expected_ids.add(PERM_SYNC_DRIVE_ADMIN_AND_USER_1_A_ID)
    expected_ids.add(PERM_SYNC_DRIVE_ADMIN_AND_USER_1_B_ID)
    expected_ids.add(TEST_USER_1_EXTRA_DRIVE_1_ID)
    expected_ids.add(TEST_USER_1_EXTRA_DRIVE_2_ID)
    expected_ids.add(ADMIN_MY_DRIVE_ID)
    expected_ids.add(PILL_FOLDER_ID)
    expected_ids.add(RESTRICTED_ACCESS_FOLDER_ID)
    expected_ids.add(TEST_USER_1_EXTRA_FOLDER_ID)

    # My Drive folders
    expected_ids.add(FOLDER_3_ID)

    assert_hierarchy_nodes_match_expected(
        retrieved_nodes=output.hierarchy_nodes,
        expected_node_ids=expected_ids,
        expected_parent_mapping=expected_parents,
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
    assert_expected_docs_in_retrieved_docs(
        retrieved_docs=output.documents,
        expected_file_ids=expected_file_ids,
    )

    # Verify hierarchy nodes - should include both shared drives and their folders
    # When include_shared_drives=True, we get ALL shared drives admin has access to
    expected_ids, expected_parents = get_expected_hierarchy_for_shared_drives(
        include_drive_1=True,
        include_drive_2=True,
        include_restricted_folder=False,
    )

    # Add additional shared drives that admin has access to
    expected_ids.add(PERM_SYNC_DRIVE_ADMIN_ONLY_ID)
    expected_ids.add(PERM_SYNC_DRIVE_ADMIN_AND_USER_1_A_ID)
    expected_ids.add(PERM_SYNC_DRIVE_ADMIN_AND_USER_1_B_ID)
    expected_ids.add(TEST_USER_1_EXTRA_DRIVE_1_ID)
    expected_ids.add(TEST_USER_1_EXTRA_DRIVE_2_ID)
    expected_ids.add(RESTRICTED_ACCESS_FOLDER_ID)

    assert_hierarchy_nodes_match_expected(
        retrieved_nodes=output.hierarchy_nodes,
        expected_node_ids=expected_ids,
        expected_parent_mapping=expected_parents,
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

    # Should only get primary_admins My Drive because we are impersonating them
    expected_file_ids = ADMIN_FILE_IDS + ADMIN_FOLDER_3_FILE_IDS
    assert_expected_docs_in_retrieved_docs(
        retrieved_docs=output.documents,
        expected_file_ids=expected_file_ids,
    )

    # Verify hierarchy nodes - My Drive should yield folder_3 as a hierarchy node
    # Also includes admin's My Drive root and folders shared with admin
    expected_ids = {
        FOLDER_3_ID,
        ADMIN_MY_DRIVE_ID,
        PILL_FOLDER_ID,
        TEST_USER_1_EXTRA_FOLDER_ID,
    }
    assert_hierarchy_nodes_match_expected(
        retrieved_nodes=output.hierarchy_nodes,
        expected_node_ids=expected_ids,
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

    # Verify hierarchy nodes - should only include shared_drive_1 and its folders
    expected_ids, expected_parents = get_expected_hierarchy_for_shared_drives(
        include_drive_1=True,
        include_drive_2=False,
        include_restricted_folder=False,
    )
    # Restricted folder is non-deterministically returned by the connector
    assert_hierarchy_nodes_match_expected(
        retrieved_nodes=output.hierarchy_nodes,
        expected_node_ids=expected_ids,
        expected_parent_mapping=expected_parents,
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

    # Verify hierarchy nodes - shared_drive_1 and folder_2 with children
    # SHARED_DRIVE_2_ID is included because folder_2's parent is shared_drive_2
    expected_ids = {
        SHARED_DRIVE_1_ID,
        FOLDER_1_ID,
        FOLDER_1_1_ID,
        FOLDER_1_2_ID,
        SHARED_DRIVE_2_ID,
        FOLDER_2_ID,
        FOLDER_2_1_ID,
        FOLDER_2_2_ID,
    }
    expected_parents = {
        SHARED_DRIVE_1_ID: None,
        FOLDER_1_ID: SHARED_DRIVE_1_ID,
        FOLDER_1_1_ID: FOLDER_1_ID,
        FOLDER_1_2_ID: FOLDER_1_ID,
        SHARED_DRIVE_2_ID: None,
        FOLDER_2_ID: SHARED_DRIVE_2_ID,
        FOLDER_2_1_ID: FOLDER_2_ID,
        FOLDER_2_2_ID: FOLDER_2_ID,
    }
    # Restricted folder is non-deterministically returned
    assert_hierarchy_nodes_match_expected(
        retrieved_nodes=output.hierarchy_nodes,
        expected_node_ids=expected_ids,
        expected_parent_mapping=expected_parents,
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
    # This should get converted to a drive request and spit out a warning in the logs
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

    # Verify hierarchy nodes - specific folders requested plus their parent nodes
    # The connector walks up the hierarchy to include parent drives/folders
    expected_ids = {
        SHARED_DRIVE_1_ID,
        FOLDER_1_ID,
        FOLDER_1_1_ID,
        FOLDER_1_2_ID,
        SHARED_DRIVE_2_ID,
        FOLDER_2_ID,
        FOLDER_2_1_ID,
        FOLDER_2_2_ID,
        ADMIN_MY_DRIVE_ID,
        FOLDER_3_ID,
    }
    assert_hierarchy_nodes_match_expected(
        retrieved_nodes=output.hierarchy_nodes,
        expected_node_ids=expected_ids,
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

    # Verify hierarchy nodes - folder_3 and its parent (admin's My Drive root)
    expected_ids = {FOLDER_3_ID, ADMIN_MY_DRIVE_ID}
    assert_hierarchy_nodes_match_expected(
        retrieved_nodes=output.hierarchy_nodes,
        expected_node_ids=expected_ids,
    )
