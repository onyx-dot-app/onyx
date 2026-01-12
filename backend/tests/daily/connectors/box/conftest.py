"""Test fixtures for Box connector tests."""

import json
import os
import resource
from collections.abc import Callable

import pytest

from onyx.connectors.box.box_kv import BOX_AUTHENTICATION_METHOD_UPLOADED
from onyx.connectors.box.box_kv import DB_CREDENTIALS_AUTHENTICATION_METHOD
from onyx.connectors.box.box_kv import DB_CREDENTIALS_DICT_BOX_JWT_CONFIG
from onyx.connectors.box.box_kv import DB_CREDENTIALS_PRIMARY_ADMIN_USER_ID
from onyx.connectors.box.connector import BoxConnector
from onyx.connectors.box.utils import parse_box_jwt_config
from tests.load_env_vars import load_env_vars


# Load environment variables at the module level
load_env_vars()


_USER_TO_PRIMARY_ADMIN_USER_ID_MAP = {
    "admin": "BOX_PRIMARY_ADMIN_USER_ID",
    "test_user_1": "BOX_PRIMARY_ADMIN_USER_ID_TEST_USER_1",
    "test_user_2": "BOX_PRIMARY_ADMIN_USER_ID_TEST_USER_2",
    "test_user_3": "BOX_PRIMARY_ADMIN_USER_ID_TEST_USER_3",
}


def get_credentials_from_env(user_key: str) -> dict:
    """
    Get Box JWT credentials from environment variables.

    Uses the same JWT config for all users, impersonating via user ID.

    Args:
        user_key (str): Key to look up user credentials (e.g., "admin", "test_user_1")

    Returns:
        dict: Credentials dictionary with JWT config and primary admin user ID
    """
    # Always use the same JWT config for all users
    raw_credential_string = os.environ["BOX_JWT_CONFIG_JSON_STR"]

    # Parse and re-serialize to ensure proper JSON formatting
    parsed_config = parse_box_jwt_config(raw_credential_string)
    normalized_credential_string = json.dumps(parsed_config)

    credentials = {
        DB_CREDENTIALS_DICT_BOX_JWT_CONFIG: normalized_credential_string,
        DB_CREDENTIALS_AUTHENTICATION_METHOD: BOX_AUTHENTICATION_METHOD_UPLOADED,
    }

    # Get the user ID for impersonation
    if user_key in _USER_TO_PRIMARY_ADMIN_USER_ID_MAP:
        primary_admin_user_id = os.environ.get(
            _USER_TO_PRIMARY_ADMIN_USER_ID_MAP[user_key]
        )
        if primary_admin_user_id:
            credentials[DB_CREDENTIALS_PRIMARY_ADMIN_USER_ID] = primary_admin_user_id

    return credentials


@pytest.fixture
def box_jwt_connector_factory() -> Callable[..., BoxConnector]:
    """
    Factory for creating Box connectors with JWT credentials.

    Similar to google_drive_service_acct_connector_factory but for Box JWT authentication.

    Note: When include_all_files=True, this factory automatically scopes to the test parent
    folder (BOX_TEST_PARENT_FOLDER_ID) instead of the Box account root to avoid loading
    all files in the account during tests.
    """

    def _connector_factory(
        user_key: str = "admin",
        include_all_files: bool = False,
        folder_ids: str | None = None,
    ) -> BoxConnector:
        print(f"Creating BoxConnector with JWT credentials for user: {user_key}")

        # For tests, when include_all_files=True, scope to test parent folder instead of root
        # This prevents loading all files in the Box account during tests
        test_parent_folder_id = os.environ.get("BOX_TEST_PARENT_FOLDER_ID")
        if include_all_files and test_parent_folder_id:
            print(
                f"Scoping include_all_files to test parent folder: {test_parent_folder_id}"
            )
            # Use folder_ids with the test parent folder instead of include_all_files
            connector = BoxConnector(
                include_all_files=False,
                folder_ids=test_parent_folder_id,
            )
        else:
            connector = BoxConnector(
                include_all_files=include_all_files,
                folder_ids=folder_ids,
            )

        credentials_json = get_credentials_from_env(user_key)
        connector.load_credentials(credentials_json)
        return connector

    return _connector_factory


@pytest.fixture
def box_connector() -> BoxConnector:
    """Create a Box connector instance for testing."""
    return BoxConnector(
        include_all_files=True,
        folder_ids=None,
    )


@pytest.fixture(scope="session", autouse=True)
def set_resource_limits() -> None:
    """
    Set resource limits for Box SDK if needed.

    Similar to Google Drive tests, this may be needed if Box SDK is aggressive
    about using file descriptors.
    """
    RLIMIT_MINIMUM = 2048
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    desired_soft = min(RLIMIT_MINIMUM, hard)

    print(f"Open file limit: soft={soft} hard={hard} soft_required={RLIMIT_MINIMUM}")

    if soft < desired_soft:
        print(f"Raising open file limit: {soft} -> {desired_soft}")
        resource.setrlimit(resource.RLIMIT_NOFILE, (desired_soft, hard))

    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    print(f"New open file limit: soft={soft} hard={hard}")
    return
