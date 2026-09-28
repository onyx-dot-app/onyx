"""A credential created for one source of a family is offered to the family's
other sources, shown in their keys."""

from typing import Any

from onyx.configs.constants import DocumentSource
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.credential import CredentialManager
from tests.integration.common_utils.test_models import DATestUser


def _similar_credentials(
    source: DocumentSource, user: DATestUser
) -> list[dict[str, Any]]:
    response = client.get(
        f"{API_SERVER_URL}/manage/admin/similar-credentials/{source.value}",
        headers=user.headers,
    )
    response.raise_for_status()
    return response.json()


def test_confluence_credential_is_listed_for_jira(admin_user: DATestUser) -> None:
    # Precondition.
    confluence_credential = CredentialManager.create(
        user_performing_action=admin_user,
        source=DocumentSource.CONFLUENCE,
        credential_json={
            "confluence_username": "user@example.com",
            "confluence_access_token": "fake-api-token",
        },
    )
    slack_credential = CredentialManager.create(
        user_performing_action=admin_user,
        source=DocumentSource.SLACK,
        credential_json={"slack_bot_token": "fake-bot-token"},
    )

    # Under test.
    jira_credentials = {
        credential["id"]: credential
        for credential in _similar_credentials(DocumentSource.JIRA, admin_user)
    }

    # Postcondition.
    assert slack_credential.id not in jira_credentials
    listed = jira_credentials[confluence_credential.id]
    assert listed["source"] == DocumentSource.CONFLUENCE.value
    assert set(listed["credential_json"]) == {"jira_user_email", "jira_api_token"}
    assert listed["usages"] == []


def test_gmail_credential_is_listed_for_google_drive(admin_user: DATestUser) -> None:
    # Precondition.
    gmail_credential = CredentialManager.create(
        user_performing_action=admin_user,
        source=DocumentSource.GMAIL,
        credential_json={
            "google_service_account_key": '{"type": "service_account"}',
            "google_primary_admin": "admin@example.com",
            "authentication_method": "uploaded",
        },
    )

    # Under test.
    drive_credentials = {
        credential["id"]: credential
        for credential in _similar_credentials(DocumentSource.GOOGLE_DRIVE, admin_user)
    }

    # Postcondition.
    listed = drive_credentials[gmail_credential.id]
    assert set(listed["credential_json"]) == {
        "google_service_account_key",
        "google_primary_admin",
        "authentication_method",
    }


def test_sharepoint_credential_is_listed_for_teams(admin_user: DATestUser) -> None:
    # Precondition.
    sharepoint_credential = CredentialManager.create(
        user_performing_action=admin_user,
        source=DocumentSource.SHAREPOINT,
        credential_json={
            "authentication_method": "client_secret",
            "sp_client_id": "fake-client-id",
            "sp_directory_id": "fake-directory-id",
            "sp_client_secret": "fake-client-secret",
        },
    )

    # Under test.
    teams_credentials = {
        credential["id"]: credential
        for credential in _similar_credentials(DocumentSource.TEAMS, admin_user)
    }

    # Postcondition.
    listed = teams_credentials[sharepoint_credential.id]
    assert set(listed["credential_json"]) == {
        "authentication_method",
        "teams_client_id",
        "teams_directory_id",
        "teams_client_secret",
    }
