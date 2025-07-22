import copy
import json
import os
from collections import defaultdict
from collections.abc import Callable
from unittest.mock import MagicMock
from unittest.mock import patch

from ee.onyx.external_permissions.google_drive.doc_sync import gdrive_doc_sync
from ee.onyx.external_permissions.google_drive.group_sync import gdrive_group_sync
from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.utils import DocumentRow
from onyx.db.utils import SortOrder
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from tests.daily.connectors.google_drive.consts_and_utils import ACCESS_MAPPING
from tests.daily.connectors.google_drive.consts_and_utils import ADMIN_EMAIL
from tests.daily.connectors.google_drive.consts_and_utils import PUBLIC_RANGE


def _build_connector(
    google_drive_service_acct_connector_factory: Callable[..., GoogleDriveConnector],
) -> GoogleDriveConnector:
    connector = google_drive_service_acct_connector_factory(
        primary_admin_email=ADMIN_EMAIL,
        include_shared_drives=True,
        include_my_drives=True,
        include_files_shared_with_me=False,
        shared_folder_urls=None,
        shared_drive_urls=None,
        my_drive_emails=None,
    )
    # don't need this anymore, it's been called in the factory
    connector.load_credentials = MagicMock()  # type: ignore
    return connector


def test_gdrive_perm_sync_with_real_data(
    google_drive_service_acct_connector_factory: Callable[..., GoogleDriveConnector],
    set_ee_on: None,
) -> None:
    """
    Test gdrive_doc_sync and gdrive_group_sync with real data from the test drive.

    This test uses the real connector to make actual API calls to Google Drive
    and verifies the permission structure returned.
    """
    # Create a mock cc_pair that will use our real connector
    mock_cc_pair = MagicMock(spec=ConnectorCredentialPair)
    mock_cc_pair.connector = MagicMock()
    mock_cc_pair.connector.connector_specific_config = {}
    mock_cc_pair.credential_id = 1
    mock_cc_pair.credential.credential_json = {}
    mock_cc_pair.last_time_perm_sync = None
    mock_cc_pair.last_time_external_group_sync = None

    # Create a mock heartbeat
    mock_heartbeat = MagicMock(spec=IndexingHeartbeatInterface)
    mock_heartbeat.should_stop.return_value = False

    # Load drive_id_mapping.json
    with open(
        os.path.join(os.path.dirname(__file__), "drive_id_mapping.json"), "r"
    ) as f:
        drive_id_mapping = json.load(f)

    # Invert the mapping to get URL -> ID
    url_to_id_mapping = {url: int(id) for id, url in drive_id_mapping.items()}

    # Use the connector directly without mocking Google Drive API calls
    with patch(
        "ee.onyx.external_permissions.google_drive.doc_sync.GoogleDriveConnector",
        return_value=_build_connector(google_drive_service_acct_connector_factory),
    ):
        # Call the function under test
        def mock_fetch_all_docs_fn(
            sort_order: SortOrder | None = None,
        ) -> list[DocumentRow]:
            return []

        def mock_fetch_all_docs_ids_fn() -> list[str]:
            return []

        doc_access_generator = gdrive_doc_sync(
            mock_cc_pair,
            mock_fetch_all_docs_fn,
            mock_fetch_all_docs_ids_fn,
            mock_heartbeat,
        )
        doc_access_list = list(doc_access_generator)

    # Verify we got some results
    assert len(doc_access_list) > 0
    print(f"Found {len(doc_access_list)} documents with permissions")

    # create new connector
    with patch(
        "ee.onyx.external_permissions.google_drive.group_sync.GoogleDriveConnector",
        return_value=_build_connector(google_drive_service_acct_connector_factory),
    ):
        external_user_group_generator = gdrive_group_sync("test_tenant", mock_cc_pair)
        external_user_groups = list(external_user_group_generator)

    # map group ids to emails
    group_id_to_email_mapping: dict[str, set[str]] = defaultdict(set)
    groups_with_anyone_access: set[str] = set()
    for group in external_user_groups:
        for email in group.user_emails:
            group_id_to_email_mapping[group.id].add(email)

        if group.gives_anyone_access:
            groups_with_anyone_access.add(group.id)

    # Map documents to their permissions (flattening groups)
    doc_to_email_mapping: dict[str, set[str]] = {}
    doc_to_raw_result_mapping: dict[str, set[str]] = {}
    public_doc_ids: set[str] = set()

    for doc_access in doc_access_list:
        doc_id = doc_access.doc_id
        # make sure they are new sets to avoid mutating the original
        doc_to_email_mapping[doc_id] = copy.deepcopy(
            doc_access.external_access.external_user_emails
        )
        doc_to_raw_result_mapping[doc_id] = copy.deepcopy(
            doc_access.external_access.external_user_emails
        )

        for group_id in doc_access.external_access.external_user_group_ids:
            doc_to_email_mapping[doc_id].update(group_id_to_email_mapping[group_id])
            doc_to_raw_result_mapping[doc_id].add(group_id)

        if doc_access.external_access.is_public:
            public_doc_ids.add(doc_id)

        if any(
            group_id in groups_with_anyone_access
            for group_id in doc_access.external_access.external_user_group_ids
        ):
            public_doc_ids.add(doc_id)

    # Check permissions based on drive_id_mapping.json and ACCESS_MAPPING
    # For each document URL that exists in our mapping
    checked_files = 0
    for doc_id, emails_with_access in doc_to_email_mapping.items():
        # Skip URLs that aren't in our mapping, we don't want new stuff to interfere
        # with the test.
        if doc_id not in url_to_id_mapping:
            continue

        file_numeric_id = url_to_id_mapping.get(doc_id)
        if file_numeric_id is None:
            raise ValueError(f"File {doc_id} not found in drive_id_mapping.json")

        checked_files += 1

        # Check which users should have access to this file according to ACCESS_MAPPING
        expected_users = set()
        for user_email, file_ids in ACCESS_MAPPING.items():
            if file_numeric_id in file_ids:
                expected_users.add(user_email)

        # Verify the permissions match
        if file_numeric_id in PUBLIC_RANGE:
            assert (
                doc_id in public_doc_ids
            ), f"File {doc_id} (ID: {file_numeric_id}) should be public but is not in the public_doc_ids set"
        else:
            assert expected_users == emails_with_access, (
                f"File {doc_id} (ID: {file_numeric_id}) should be accessible to users {expected_users} "
                f"but is accessible to {emails_with_access}. Raw result: {doc_to_raw_result_mapping[doc_id]} "
            )

    # Verify that we checked every file in ACCESS_MAPPING
    all_expected_files = set()
    for file_ids in ACCESS_MAPPING.values():
        all_expected_files.update(file_ids)

    checked_file_ids = {
        url_to_id_mapping[doc_id]
        for doc_id in doc_to_email_mapping
        if doc_id in url_to_id_mapping
    }

    assert all_expected_files == checked_file_ids, (
        f"Not all expected files were checked. "
        f"Missing files: {all_expected_files - checked_file_ids}, "
        f"Extra files checked: {checked_file_ids - all_expected_files}"
    )

    print(f"Checked permissions for {checked_files} files from drive_id_mapping.json")
