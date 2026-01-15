"""Permission sync tests for Box connector."""

import copy
from collections.abc import Callable
from unittest.mock import MagicMock
from unittest.mock import patch
from urllib.parse import urlparse

from ee.onyx.external_permissions.box.doc_sync import box_doc_sync
from onyx.connectors.box.connector import BoxConnector
from onyx.db.models import ConnectorCredentialPair
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from tests.daily.connectors.box.consts_and_utils import ACCESS_MAPPING
from tests.daily.connectors.box.consts_and_utils import PUBLIC_RANGE


def _build_connector(
    box_jwt_connector_factory: Callable[..., BoxConnector],
) -> BoxConnector:
    """Build a Box connector for permission sync testing."""
    return box_jwt_connector_factory(
        user_key="admin",
        include_all_files=True,
        folder_ids=None,
    )


def test_box_perm_sync_with_real_data(
    box_jwt_connector_factory: Callable[..., BoxConnector],
    set_ee_on: None,
) -> None:
    """
    Test box_doc_sync with real data from the test Box account.

    This test uses the real connector to make actual API calls to Box
    and verifies the permission structure returned.
    """
    # Create a mock cc_pair that will use our real connector
    # For tests, scope to test parent folder instead of root
    import os
    from tests.daily.connectors.box.conftest import get_credentials_from_env

    test_parent_folder_id = os.environ.get("BOX_TEST_PARENT_FOLDER_ID")
    mock_cc_pair = MagicMock(spec=ConnectorCredentialPair)
    mock_cc_pair.connector = MagicMock()
    if test_parent_folder_id:
        mock_cc_pair.connector.connector_specific_config = {
            "include_all_files": False,
            "folder_ids": test_parent_folder_id,
        }
    else:
        mock_cc_pair.connector.connector_specific_config = {
            "include_all_files": True,
            "folder_ids": None,
        }
    mock_cc_pair.credential_id = 1
    # Use real credentials from environment
    mock_cc_pair.credential.credential_json = get_credentials_from_env("admin")
    mock_cc_pair.last_time_perm_sync = None

    # Create a mock heartbeat
    mock_heartbeat = MagicMock(spec=IndexingHeartbeatInterface)
    mock_heartbeat.should_stop.return_value = False

    # Use the connector directly without mocking Box API calls
    # Create a connector factory that respects the test scoping
    def connector_factory(**kwargs):
        # Use the connector_specific_config from mock_cc_pair to respect test scoping
        config = mock_cc_pair.connector.connector_specific_config
        return box_jwt_connector_factory(
            user_key="admin",
            include_all_files=config.get("include_all_files", True),
            folder_ids=config.get("folder_ids", None),
        )

    with patch(
        "ee.onyx.external_permissions.box.doc_sync.BoxConnector",
        side_effect=connector_factory,
    ):
        # Call the function under test
        mock_fetch_all_docs_fn = MagicMock(return_value=[])
        mock_fetch_all_docs_ids_fn = MagicMock(return_value=[])

        doc_access_generator = box_doc_sync(
            mock_cc_pair,
            mock_fetch_all_docs_fn,
            mock_fetch_all_docs_ids_fn,
            mock_heartbeat,
        )
        doc_access_list = list(doc_access_generator)

    # Verify we got some results
    assert len(doc_access_list) > 0
    print(f"Found {len(doc_access_list)} documents with permissions")

    # Map documents to their permissions
    doc_to_user_id_mapping: dict[str, set[str]] = {}
    doc_to_raw_result_mapping: dict[str, set[str]] = {}
    public_doc_ids: set[str] = set()

    for doc_access in doc_access_list:
        doc_id = doc_access.doc_id
        # make sure they are new sets to avoid mutating the original
        doc_to_user_id_mapping[doc_id] = copy.deepcopy(
            doc_access.external_access.external_user_emails
        )
        doc_to_raw_result_mapping[doc_id] = copy.deepcopy(
            doc_access.external_access.external_user_emails
        )

        # Box uses user emails directly, not groups like Google Drive
        # But we may have group IDs that need to be resolved
        for group_id in doc_access.external_access.external_user_group_ids:
            # For Box, group IDs might need to be resolved to user emails
            # This would require additional group sync functionality
            doc_to_raw_result_mapping[doc_id].add(group_id)

        if doc_access.external_access.is_public:
            public_doc_ids.add(doc_id)

    # Build mapping from document URLs to test file IDs on the fly
    # Extract Box file ID from URL and fetch file metadata to get name, then extract test ID
    from onyx.utils.logger import setup_logger

    logger = setup_logger()
    url_to_id_mapping: dict[str, int] = {}

    # Get Box client from the connector to fetch file metadata
    connector_for_metadata = connector_factory()
    box_client = connector_for_metadata.box_client

    # Build mapping by extracting file IDs from URLs and fetching metadata
    print("Building file ID mapping on the fly...")
    for doc_access in doc_access_list:
        doc_id = doc_access.doc_id
        # Extract Box file ID from URL (format: https://app.box.com/file/{file_id})
        parsed = urlparse(doc_id)
        path_parts = parsed.path.strip("/").split("/")
        if len(path_parts) >= 2 and path_parts[0] == "file":
            box_file_id = path_parts[1]
            try:
                # Fetch file metadata to get the name
                file_info = box_client.files.get_file_by_id(
                    box_file_id, fields=["name"]
                )
                file_name = file_info.name

                # Extract test file ID from filename (e.g., "file_0.txt" -> 0)
                if file_name.startswith("file_") and ".txt" in file_name:
                    test_id_str = file_name.split("_")[1].split(".")[0]
                    try:
                        test_file_id = int(test_id_str)
                        url_to_id_mapping[doc_id] = test_file_id
                    except ValueError:
                        # Not a test file, skip
                        pass
            except Exception as e:
                # If we can't fetch metadata, skip this file
                # (might not have access or file might not exist)
                logger.debug(f"Could not fetch metadata for file {box_file_id}: {e}")
                continue

    print(f"Built mapping for {len(url_to_id_mapping)} test files")

    # Check permissions based on ACCESS_MAPPING
    # For each document URL that exists in our mapping (test files only)
    checked_files = 0
    for doc_id, user_ids_with_access in doc_to_user_id_mapping.items():
        # Skip URLs that aren't in our mapping, we don't want new stuff to interfere
        # with the test.
        if doc_id not in url_to_id_mapping:
            continue

        file_numeric_id = url_to_id_mapping.get(doc_id)
        if file_numeric_id is None:
            # This shouldn't happen since we just built the mapping, but handle it gracefully
            continue

        checked_files += 1

        # Check which users should have access to this file according to ACCESS_MAPPING
        # Note: ACCESS_MAPPING uses user IDs (e.g., "13089353657"), but Box permissions
        # return user emails (e.g., "admin@onyx-test.com"). We need to verify access
        # by checking that the expected number of users have access, rather than
        # exact email matching (which would require a user ID to email mapping).
        expected_user_count = 0
        for user_id, file_ids in ACCESS_MAPPING.items():
            if file_numeric_id in file_ids:
                expected_user_count += 1

        # Verify the permissions match
        if file_numeric_id in PUBLIC_RANGE:
            # Public files should be marked as public
            assert (
                doc_id in public_doc_ids
            ), f"File {doc_id} (ID: {file_numeric_id}) should be public but is not in the public_doc_ids set"
            # Public files may have additional user access, so we just verify it's marked public
        else:
            # Non-public files should have at least the expected number of users with access
            # Note: We can't do exact email matching without a user ID to email mapping,
            # but we can verify that files have the expected level of access
            # Check both user emails and group IDs (files may have group-only permissions)
            has_user_access = len(user_ids_with_access) > 0
            has_group_access = len(doc_to_raw_result_mapping[doc_id]) > len(
                user_ids_with_access
            )
            assert has_user_access or has_group_access, (
                f"File {doc_id} (ID: {file_numeric_id}) should have some access "
                f"(user emails or group IDs) but has none. "
                f"User emails: {user_ids_with_access}, "
                f"Raw result (includes groups): {doc_to_raw_result_mapping[doc_id]}"
            )

            # Verify that the number of users with access is at least the expected count
            # (some files may have additional access beyond what's in ACCESS_MAPPING)
            assert len(user_ids_with_access) >= expected_user_count, (
                f"File {doc_id} (ID: {file_numeric_id}) should have access for at least "
                f"{expected_user_count} user(s) according to ACCESS_MAPPING, "
                f"but only {len(user_ids_with_access)} user(s) have access. "
                f"Users with access: {user_ids_with_access}. "
                f"Raw result: {doc_to_raw_result_mapping[doc_id]}"
            )

            # Log the access for debugging (helps identify permission issues)
            if len(user_ids_with_access) != expected_user_count:
                print(
                    f"Note: File {doc_id} (ID: {file_numeric_id}) has {len(user_ids_with_access)} "
                    f"users with access, expected {expected_user_count} from ACCESS_MAPPING. "
                    f"This may be due to additional sharing or group permissions."
                )

    if checked_files > 0:
        print(f"Checked permissions for {checked_files} test files")
    else:
        # If no files were checked, it means no test files (file_*.txt) were found
        # This is a critical failure - the test cannot validate permissions without test files
        assert False, (
            f"No test files (file_*.txt) found to validate permissions. "
            f"Found {len(doc_access_list)} documents total, but none matched the test file pattern. "
            f"This test validates permissions for files matching 'file_*.txt' pattern."
        )


def test_slim_document_generation(
    box_jwt_connector_factory: Callable[..., BoxConnector],
) -> None:
    """Test slim document generation for permission sync."""
    connector = box_jwt_connector_factory(
        user_key="admin",
        include_all_files=True,
        folder_ids=None,
    )

    # Test that retrieve_all_slim_docs_perm_sync works
    # Add safety limit to prevent infinite loops
    slim_doc_generator = connector.retrieve_all_slim_docs_perm_sync()

    slim_doc_batches = []
    max_iterations = 1000  # Safety limit
    iteration_count = 0

    for batch in slim_doc_generator:
        slim_doc_batches.append(batch)
        iteration_count += 1
        if iteration_count >= max_iterations:
            raise RuntimeError(
                f"Test hit safety limit of {max_iterations} iterations. "
                "This suggests an infinite loop."
            )

    # Should get some slim documents
    assert len(slim_doc_batches) > 0

    # Each batch should contain slim documents
    for batch in slim_doc_batches:
        assert len(batch) > 0
        for slim_doc in batch:
            assert slim_doc.id is not None
            # External access may or may not be present
            # depending on whether permissions were fetched


def test_permission_sync_checkpointing(
    box_jwt_connector_factory: Callable[..., BoxConnector],
) -> None:
    """Test permission sync with checkpointing."""
    connector = box_jwt_connector_factory(
        user_key="admin",
        include_all_files=True,
        folder_ids=None,
    )

    # Load slim docs with checkpointing using the proper method
    import time

    start_time = 0
    end_time = time.time()

    # Use retrieve_all_slim_docs_perm_sync which properly handles checkpointing
    slim_doc_generator = connector.retrieve_all_slim_docs_perm_sync(
        start=start_time,
        end=end_time,
        callback=None,
    )

    # Collect batches with a safety limit to prevent infinite loops
    slim_doc_batches = []
    max_iterations = 1000  # Safety limit
    iteration_count = 0

    for batch in slim_doc_generator:
        slim_doc_batches.append(batch)
        iteration_count += 1
        if iteration_count >= max_iterations:
            # If we hit the limit, something is wrong
            raise RuntimeError(
                f"Test hit safety limit of {max_iterations} iterations. "
                "This suggests an infinite loop or checkpoint not updating properly."
            )

    # Should get some documents
    assert len(slim_doc_batches) > 0
    # Verify we got some slim documents
    total_docs = sum(len(batch) for batch in slim_doc_batches)
    assert total_docs > 0, "Should have retrieved at least one slim document"
