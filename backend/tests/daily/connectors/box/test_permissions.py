"""Permission and access tests for Box connector."""

from collections.abc import Callable
from unittest.mock import MagicMock
from unittest.mock import patch

from box_sdk_gen.box import BoxAPIError

from onyx.connectors.box.connector import BoxConnector
from tests.daily.connectors.box.consts_and_utils import ACCESS_MAPPING
from tests.daily.connectors.box.consts_and_utils import ADMIN_FOLDER_3_FILE_IDS
from tests.daily.connectors.box.consts_and_utils import ADMIN_FOLDER_3_URL
from tests.daily.connectors.box.consts_and_utils import ADMIN_USER_ID
from tests.daily.connectors.box.consts_and_utils import (
    assert_expected_docs_in_retrieved_docs,
)
from tests.daily.connectors.box.consts_and_utils import FOLDER_1_1_FILE_IDS
from tests.daily.connectors.box.consts_and_utils import FOLDER_1_2_FILE_IDS
from tests.daily.connectors.box.consts_and_utils import FOLDER_1_FILE_IDS
from tests.daily.connectors.box.consts_and_utils import FOLDER_1_URL
from tests.daily.connectors.box.consts_and_utils import FOLDER_3_URL
from tests.daily.connectors.box.consts_and_utils import load_all_docs
from tests.daily.connectors.box.consts_and_utils import TEST_USER_1_ID


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_user_access_mapping(
    mock_get_api_key: MagicMock,
    box_jwt_connector_factory: Callable[..., BoxConnector],
) -> None:
    """Test that files are only accessible to users with permissions."""
    # Test with admin user - should have access to everything
    admin_connector = box_jwt_connector_factory(
        user_key="admin",
        include_all_files=True,
        folder_ids=None,
    )
    admin_docs = load_all_docs(admin_connector)
    admin_file_ids = list(ACCESS_MAPPING[ADMIN_USER_ID])
    assert_expected_docs_in_retrieved_docs(
        retrieved_docs=admin_docs,
        expected_file_ids=admin_file_ids,
    )

    # Test with test_user_1 - should have limited access
    user1_connector = box_jwt_connector_factory(
        user_key="test_user_1",
        include_all_files=True,
        folder_ids=None,
    )
    user1_docs = load_all_docs(user1_connector)
    user1_file_ids = list(ACCESS_MAPPING[TEST_USER_1_ID])
    assert_expected_docs_in_retrieved_docs(
        retrieved_docs=user1_docs,
        expected_file_ids=user1_file_ids,
    )

    # Verify that user1's expected files are a subset of admin's expected files
    # (When scoped to test parent folder, all users can see all subfolders)
    assert set(user1_file_ids).issubset(set(admin_file_ids))


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_public_files(
    mock_get_api_key: MagicMock,
    box_jwt_connector_factory: Callable[..., BoxConnector],
) -> None:
    """Test that public files are accessible to all users."""
    from tests.daily.connectors.box.consts_and_utils import PUBLIC_RANGE
    from tests.daily.connectors.box.consts_and_utils import id_to_name

    # Test with admin
    admin_connector = box_jwt_connector_factory(
        user_key="admin",
        include_all_files=True,
        folder_ids=None,
    )
    admin_docs = load_all_docs(admin_connector)
    admin_file_names = {doc.semantic_identifier for doc in admin_docs}

    # Test with test_user_3 (most restricted user)
    # Use FOLDER_1_2 which is public and accessible to all users
    from tests.daily.connectors.box.consts_and_utils import FOLDER_1_2_URL

    user3_connector = box_jwt_connector_factory(
        user_key="test_user_3",
        include_all_files=False,
        folder_ids=FOLDER_1_2_URL,
    )
    user3_docs = load_all_docs(user3_connector)
    user3_file_names = {doc.semantic_identifier for doc in user3_docs}

    # Verify that public files are accessible to both users
    # PUBLIC_RANGE includes FOLDER_1_2_FILE_IDS (public folder) and PUBLIC_FILE_IDS
    # test_user_3 only has access to FOLDER_1_2, so we verify that subset
    expected_public_file_names = {id_to_name(file_id) for file_id in PUBLIC_RANGE}

    admin_public_files = admin_file_names & expected_public_file_names
    user3_public_files = user3_file_names & expected_public_file_names

    # Verify test_user_3 has access to the public folder files
    from tests.daily.connectors.box.consts_and_utils import FOLDER_1_2_FILE_IDS

    expected_folder_1_2_names = {id_to_name(file_id) for file_id in FOLDER_1_2_FILE_IDS}

    # test_user_3 should have access to all files in the public folder
    assert expected_folder_1_2_names.issubset(user3_public_files), (
        f"test_user_3 should have access to all files in public folder FOLDER_1_2. "
        f"Expected: {expected_folder_1_2_names}, Got: {user3_public_files}"
    )

    # Admin should also have access to the public folder files
    assert expected_folder_1_2_names.issubset(admin_public_files), (
        f"Admin should have access to all files in public folder FOLDER_1_2. "
        f"Expected: {expected_folder_1_2_names}, Got: {admin_public_files}"
    )

    # At least some public files should exist
    assert len(user3_public_files) > 0, (
        f"test_user_3 should have access to at least some public files. "
        f"Got: {user3_public_files}"
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_restricted_access(
    mock_get_api_key: MagicMock,
    box_jwt_connector_factory: Callable[..., BoxConnector],
) -> None:
    """Test files with restricted access."""
    # Test with admin - should have access
    admin_connector = box_jwt_connector_factory(
        user_key="admin",
        include_all_files=False,
        folder_ids=FOLDER_3_URL,
    )
    admin_docs = load_all_docs(admin_connector)
    assert len(admin_docs) > 0

    # Test with test_user_3 - should not have access to admin's folder 3 (ADMIN_FOLDER_3)
    # The setup script explicitly removes test_user_3's access to ensure this test is useful
    user3_connector = box_jwt_connector_factory(
        user_key="test_user_3",
        include_all_files=False,
        folder_ids=ADMIN_FOLDER_3_URL,
    )
    # When a user doesn't have access, Box returns a 404 error
    try:
        user3_docs = load_all_docs(user3_connector)
        assert len(user3_docs) == 0, (
            f"test_user_3 should not have access to ADMIN_FOLDER_3, "
            f"but retrieved {len(user3_docs)} files. "
            f"Run setup script to ensure test_user_3's access is removed."
        )
    except BoxAPIError as e:
        # 404 error indicates no access (expected behavior)
        status_code = getattr(e, "status_code", None)
        if status_code != 404:
            raise
    except Exception as e:
        # For non-BoxAPIError exceptions, check if it's a wrapped 404
        # This handles cases where BoxAPIError might be wrapped
        error_msg = str(e).lower()
        if (
            "404" not in error_msg
            and "not found" not in error_msg
            and "not_found" not in error_msg
        ):
            raise


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_collaboration_permissions(
    mock_get_api_key: MagicMock,
    box_jwt_connector_factory: Callable[..., BoxConnector],
) -> None:
    """Test Box collaboration permissions."""
    # Test that test_user_1 has access to admin's folder 3 (shared via collaboration)
    user1_connector = box_jwt_connector_factory(
        user_key="test_user_1",
        include_all_files=False,
        folder_ids=ADMIN_FOLDER_3_URL,
    )
    user1_docs = load_all_docs(user1_connector)
    # Should have access to files in admin's folder 3
    expected_file_ids = ADMIN_FOLDER_3_FILE_IDS
    assert_expected_docs_in_retrieved_docs(
        retrieved_docs=user1_docs,
        expected_file_ids=expected_file_ids,
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_shared_folders(
    mock_get_api_key: MagicMock,
    box_jwt_connector_factory: Callable[..., BoxConnector],
) -> None:
    """Test files in shared folders."""
    # Test that test_user_2 has access to folder 1 (shared via group)
    user2_connector = box_jwt_connector_factory(
        user_key="test_user_2",
        include_all_files=False,
        folder_ids=FOLDER_1_URL,
    )
    user2_docs = load_all_docs(user2_connector)
    # Should have access to files in folder 1
    expected_file_ids = FOLDER_1_FILE_IDS + FOLDER_1_1_FILE_IDS + FOLDER_1_2_FILE_IDS
    assert_expected_docs_in_retrieved_docs(
        retrieved_docs=user2_docs,
        expected_file_ids=expected_file_ids,
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_user_specific_access(
    mock_get_api_key: MagicMock,
    box_jwt_connector_factory: Callable[..., BoxConnector],
) -> None:
    """Test that users can only access their own files and shared files."""
    # Test with test_user_3 (most restricted)
    # test_user_3 should have access to public folder FOLDER_1_2
    # but should NOT have access to ADMIN_FOLDER_3 (restricted)
    from tests.daily.connectors.box.consts_and_utils import FOLDER_1_2_URL

    user3_connector = box_jwt_connector_factory(
        user_key="test_user_3",
        include_all_files=False,
        folder_ids=FOLDER_1_2_URL,
    )
    user3_docs = load_all_docs(user3_connector)
    # test_user_3 should have access to public folder FOLDER_1_2
    # Verify they can access the public files in that folder
    expected_file_ids = FOLDER_1_2_FILE_IDS  # Public folder files
    assert_expected_docs_in_retrieved_docs(
        retrieved_docs=user3_docs,
        expected_file_ids=expected_file_ids,
    )

    # Verify test_user_3 does NOT have access to ADMIN_FOLDER_3
    user3_restricted_connector = box_jwt_connector_factory(
        user_key="test_user_3",
        include_all_files=False,
        folder_ids=ADMIN_FOLDER_3_URL,
    )
    try:
        restricted_docs = load_all_docs(user3_restricted_connector)
        # If no exception, verify no documents were retrieved
        assert len(restricted_docs) == 0, (
            f"test_user_3 should NOT have access to ADMIN_FOLDER_3, "
            f"but retrieved {len(restricted_docs)} files: {[doc.semantic_identifier for doc in restricted_docs]}"
        )
    except BoxAPIError as e:
        # If a BoxAPIError is raised with 404, that means test_user_3
        # doesn't have access, which is what we want. The test passes.
        status_code = getattr(e, "status_code", None)
        if status_code != 404:
            # Unexpected status code, re-raise it
            raise
    except Exception as e:
        # For non-BoxAPIError exceptions, check if it's a wrapped 404
        # This handles cases where BoxAPIError might be wrapped
        error_msg = str(e).lower()
        if (
            "404" not in error_msg
            and "not found" not in error_msg
            and "not_found" not in error_msg
        ):
            # Unexpected error, re-raise it
            raise
