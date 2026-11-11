from unittest.mock import MagicMock, patch

import pytest
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials

from onyx.connectors.google_utils.resources import GoogleService, get_google_service


@pytest.mark.parametrize(
    ("service", "api_name", "api_version"),
    [
        (GoogleService.DOCS, "docs", "v1"),
        (GoogleService.DRIVE, "drive", "v3"),
        (GoogleService.ADMIN, "admin", "directory_v1"),
        (GoogleService.GMAIL, "gmail", "v1"),
    ],
)
@pytest.mark.parametrize("service_account", [False, True])
def test_google_service_preserves_api_and_credentials(
    service: GoogleService,
    api_name: str,
    api_version: str,
    service_account: bool,
) -> None:
    creds = MagicMock(
        spec=ServiceAccountCredentials if service_account else OAuthCredentials
    )
    user_email = "user@example.com"
    with patch("onyx.connectors.google_utils.resources.build") as build:
        resource = get_google_service(service, creds, user_email)

    expected_creds = creds.with_subject.return_value if service_account else creds
    build.assert_called_once_with(api_name, api_version, credentials=expected_creds)
    assert resource is build.return_value
    if service_account:
        creds.with_subject.assert_called_once_with(user_email)
