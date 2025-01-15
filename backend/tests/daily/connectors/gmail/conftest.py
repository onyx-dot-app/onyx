import json
import os
from collections.abc import Callable

import pytest

from onyx.connectors.gmail.connector import GmailConnector
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
def google_gmail_oauth_connector_factory() -> Callable[..., GmailConnector]:
    def _connector_factory(
        primary_admin_email: str = "admin@onyx-test.com",
    ) -> GmailConnector:
        print("Creating GmailConnector with OAuth credentials")
        connector = GmailConnector()

        json_string = os.environ["GOOGLE_GMAIL_OAUTH_CREDENTIALS_JSON_STR"]
        refried_json_string = json.dumps(parse_credentials(json_string))

        credentials_json = {
            DB_CREDENTIALS_DICT_TOKEN_KEY: refried_json_string,
            DB_CREDENTIALS_PRIMARY_ADMIN_KEY: primary_admin_email,
            DB_CREDENTIALS_AUTHENTICATION_METHOD: GoogleOAuthAuthenticationMethod.UPLOADED.value,
        }
        connector.load_credentials(credentials_json)
        return connector

    return _connector_factory


@pytest.fixture
def google_gmail_service_acct_connector_factory() -> Callable[..., GmailConnector]:
    def _connector_factory(
        primary_admin_email: str = "admin@onyx-test.com",
    ) -> GmailConnector:
        print("Creating GmailConnector with service account credentials")
        connector = GmailConnector()

        json_string = os.environ["GOOGLE_GMAIL_SERVICE_ACCOUNT_JSON_STR"]
        refried_json_string = json.dumps(parse_credentials(json_string))

        # Load Service Account Credentials
        connector.load_credentials(
            {
                DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY: refried_json_string,
                DB_CREDENTIALS_PRIMARY_ADMIN_KEY: primary_admin_email,
                DB_CREDENTIALS_AUTHENTICATION_METHOD: GoogleOAuthAuthenticationMethod.UPLOADED.value,
            }
        )
        return connector

    return _connector_factory
