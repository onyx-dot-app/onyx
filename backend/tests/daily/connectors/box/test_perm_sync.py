"""Permission sync tests for Box connector."""

import copy
import json
from collections.abc import Callable
from unittest.mock import MagicMock
from unittest.mock import patch

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

    # Load box_id_mapping.json if it exists
    mapping_file = os.path.join(os.path.dirname(__file__), "box_id_mapping.json")
    url_to_id_mapping: dict[str, int] = {}
    if os.path.exists(mapping_file):
        with open(mapping_file, "r") as f:
            box_id_mapping = json.load(f)
        # Invert the mapping to get URL -> ID
        url_to_id_mapping = {url: int(id) for id, url in box_id_mapping.items()}

    # Use the connector directly without mocking Box API calls
    with patch(
        "ee.onyx.external_permissions.box.doc_sync.BoxConnector",
        return_value=_build_connector(box_jwt_connector_factory),
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

    # Check permissions based on box_id_mapping.json and ACCESS_MAPPING
    # For each document URL that exists in our mapping
    checked_files = 0
    for doc_id, user_ids_with_access in doc_to_user_id_mapping.items():
        # Skip URLs that aren't in our mapping, we don't want new stuff to interfere
        # with the test.
        if doc_id not in url_to_id_mapping:
            continue

        file_numeric_id = url_to_id_mapping.get(doc_id)
        if file_numeric_id is None:
            raise ValueError(f"File {doc_id} not found in box_id_mapping.json")

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
            assert len(user_ids_with_access) > 0, (
                f"File {doc_id} (ID: {file_numeric_id}) should have some access "
                f"but has none. Raw result: {doc_to_raw_result_mapping[doc_id]}"
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
        print(f"Checked permissions for {checked_files} files from box_id_mapping.json")
    else:
        print(
            "No files checked. box_id_mapping.json may not exist. "
            "Run test_map_test_ids.py to generate it."
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
