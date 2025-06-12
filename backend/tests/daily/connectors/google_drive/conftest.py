import json
import os
import resource
from collections.abc import Callable

import pytest

from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_AUTHENTICATION_METHOD,
)
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY,
)
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_DICT_TOKEN_KEY,
)
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY,
)
from onyx.connectors.google_utils.shared_constants import (
    GoogleOAuthAuthenticationMethod,
)
from tests.load_env_vars import load_env_vars


# Load environment variables at the module level
load_env_vars()


_USER_TO_OAUTH_CREDENTIALS_MAP = {
    "admin@onyx-test.com": "GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON_STR",
    "test_user_1@onyx-test.com": "GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON_STR_TEST_USER_1",
}

_USER_TO_SERVICE_ACCOUNT_CREDENTIALS_MAP = {
    "admin@onyx-test.com": "GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON_STR",
}


def parse_credentials(env_str: str) -> dict:
    """
    Parse a double-escaped JSON string from environment variables into a Python dictionary.

    Args:
        env_str (str): The double-escaped JSON string from environment variables

    Returns:
        dict: Parsed OAuth credentials
    """
    # first try normally
    try:
        return json.loads(env_str)
    except Exception:
        # First, try remove extra escaping backslashes
        unescaped = env_str.replace('\\"', '"')

        # remove leading / trailing quotes
        unescaped = unescaped.strip('"')

        # Now parse the JSON
        return json.loads(unescaped)


def get_credentials_from_env(email: str, oauth: bool) -> dict:
    if oauth:
        raw_credential_string = os.environ[_USER_TO_OAUTH_CREDENTIALS_MAP[email]]
    else:
        raw_credential_string = os.environ[
            _USER_TO_SERVICE_ACCOUNT_CREDENTIALS_MAP[email]
        ]

    refried_credential_string = json.dumps(parse_credentials(raw_credential_string))

    cred_key = (
        DB_CREDENTIALS_DICT_TOKEN_KEY
        if oauth
        else DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY
    )
    return {
        cred_key: refried_credential_string,
        DB_CREDENTIALS_PRIMARY_ADMIN_KEY: email,
        DB_CREDENTIALS_AUTHENTICATION_METHOD: GoogleOAuthAuthenticationMethod.UPLOADED.value,
    }


@pytest.fixture
def google_drive_oauth_uploaded_connector_factory() -> (
    Callable[..., GoogleDriveConnector]
):
    def _connector_factory(
        primary_admin_email: str,
        include_shared_drives: bool,
        shared_drive_urls: str | None,
        include_my_drives: bool,
        my_drive_emails: str | None,
        shared_folder_urls: str | None,
        include_files_shared_with_me: bool,
    ) -> GoogleDriveConnector:
        print("Creating GoogleDriveConnector with OAuth credentials")
        connector = GoogleDriveConnector(
            include_shared_drives=include_shared_drives,
            shared_drive_urls=shared_drive_urls,
            include_my_drives=include_my_drives,
            include_files_shared_with_me=include_files_shared_with_me,
            my_drive_emails=my_drive_emails,
            shared_folder_urls=shared_folder_urls,
        )

        credentials_json = get_credentials_from_env(primary_admin_email, oauth=True)
        connector.load_credentials(credentials_json)
        return connector

    return _connector_factory


@pytest.fixture
def google_drive_service_acct_connector_factory() -> (
    Callable[..., GoogleDriveConnector]
):
    def _connector_factory(
        primary_admin_email: str,
        include_shared_drives: bool,
        shared_drive_urls: str | None,
        include_my_drives: bool,
        my_drive_emails: str | None,
        shared_folder_urls: str | None,
        include_files_shared_with_me: bool,
        specific_user_emails: str | None = None,
    ) -> GoogleDriveConnector:
        print("Creating GoogleDriveConnector with service account credentials")
        connector = GoogleDriveConnector(
            include_shared_drives=include_shared_drives,
            shared_drive_urls=shared_drive_urls,
            include_my_drives=include_my_drives,
            my_drive_emails=my_drive_emails,
            shared_folder_urls=shared_folder_urls,
            include_files_shared_with_me=include_files_shared_with_me,
            specific_user_emails=specific_user_emails,
        )

        # Load Service Account Credentials
        credentials_json = get_credentials_from_env(
            email=primary_admin_email, oauth=False
        )
        connector.load_credentials(credentials_json)
        return connector

    return _connector_factory


@pytest.fixture(scope="session", autouse=True)
def set_resource_limits() -> None:
    # the google sdk is aggressive about using up file descriptors and
    # macos is stingy ... these tests will fail randomly unless the descriptor limit is raised
    RLIMIT_MINIMUM = 2048
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    desired_soft = min(RLIMIT_MINIMUM, hard)  # Pick your target here

    print(f"Open file limit: soft={soft} hard={hard} soft_required={RLIMIT_MINIMUM}")

    if soft < desired_soft:
        print(f"Raising open file limit: {soft} -> {desired_soft}")
        resource.setrlimit(resource.RLIMIT_NOFILE, (desired_soft, hard))

    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    print(f"New open file limit: soft={soft} hard={hard}")
    return
