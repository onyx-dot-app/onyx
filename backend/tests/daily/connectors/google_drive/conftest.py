import json
import os
from collections.abc import Callable

import pytest

from danswer.connectors.google_drive.connector import GoogleDriveConnector
from danswer.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY,
)
from danswer.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_DICT_TOKEN_KEY,
)
from danswer.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY,
)
from tests.load_env_vars import load_env_vars


# Load environment variables at the module level
load_env_vars()


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


@pytest.fixture
def google_drive_oauth_connector_factory() -> Callable[..., GoogleDriveConnector]:
    def _connector_factory(
        primary_admin_email: str = "admin@onyx-test.com",
        include_shared_drives: bool = True,
        shared_drive_urls: str | None = None,
        include_my_drives: bool = True,
        my_drive_emails: str | None = None,
        shared_folder_urls: str | None = None,
    ) -> GoogleDriveConnector:
        print("Creating GoogleDriveConnector with OAuth credentials")
        connector = GoogleDriveConnector(
            include_shared_drives=include_shared_drives,
            shared_drive_urls=shared_drive_urls,
            include_my_drives=include_my_drives,
            my_drive_emails=my_drive_emails,
            shared_folder_urls=shared_folder_urls,
        )

        json_string = os.environ["GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON_STR"]
        refried_json_string = json.dumps(parse_credentials(json_string))

        credentials_json = {
            DB_CREDENTIALS_DICT_TOKEN_KEY: refried_json_string,
            DB_CREDENTIALS_PRIMARY_ADMIN_KEY: primary_admin_email,
        }
        connector.load_credentials(credentials_json)
        return connector

    return _connector_factory


@pytest.fixture
def google_drive_service_acct_connector_factory() -> (
    Callable[..., GoogleDriveConnector]
):
    def _connector_factory(
        primary_admin_email: str = "admin@onyx-test.com",
        include_shared_drives: bool = True,
        shared_drive_urls: str | None = None,
        include_my_drives: bool = True,
        my_drive_emails: str | None = None,
        shared_folder_urls: str | None = None,
    ) -> GoogleDriveConnector:
        print("Creating GoogleDriveConnector with service account credentials")
        connector = GoogleDriveConnector(
            include_shared_drives=include_shared_drives,
            shared_drive_urls=shared_drive_urls,
            include_my_drives=include_my_drives,
            my_drive_emails=my_drive_emails,
            shared_folder_urls=shared_folder_urls,
        )

        json_string = os.environ["GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON_STR"]
        refried_json_string = json.dumps(parse_credentials(json_string))

        # Load Service Account Credentials
        connector.load_credentials(
            {
                DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY: refried_json_string,
                DB_CREDENTIALS_PRIMARY_ADMIN_KEY: primary_admin_email,
            }
        )
        return connector

    return _connector_factory
