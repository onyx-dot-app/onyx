from typing import Any

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.credential_families import (
    is_credential_usable_for_source,
    to_source_credential_json,
    to_stored_credential_json,
)
from onyx.connectors.credential_family_base import CREDENTIAL_FAMILY_KEY

_CONFLUENCE_JSON: dict[str, Any] = {
    "confluence_username": "user@example.com",
    "confluence_access_token": "token",
}


def test_new_family_credential_is_stored_in_the_family_shape() -> None:
    stored = to_stored_credential_json(
        DocumentSource.CONFLUENCE, _CONFLUENCE_JSON, None
    )

    assert stored == {
        "email": "user@example.com",
        "token": "token",
        "oauth": None,
        CREDENTIAL_FAMILY_KEY: "atlassian",
    }
    assert to_source_credential_json(DocumentSource.JIRA, stored) == {
        "jira_user_email": "user@example.com",
        "jira_api_token": "token",
    }
    assert to_source_credential_json(DocumentSource.CONFLUENCE, stored) == (
        _CONFLUENCE_JSON
    )
    assert is_credential_usable_for_source(
        DocumentSource.CONFLUENCE, stored, DocumentSource.JIRA
    )


@pytest.mark.parametrize("email", ["user@example.com", ""])
def test_jsm_credential_shares_jira_family_and_round_trips(email: str) -> None:
    source_json = {"jira_user_email": email, "jira_api_token": "token"}
    stored = to_stored_credential_json(
        DocumentSource.JIRA_SERVICE_MANAGEMENT, source_json, None
    )
    expected = {"jira_api_token": "token"}
    if email:
        expected["jira_user_email"] = email

    assert (
        to_source_credential_json(DocumentSource.JIRA_SERVICE_MANAGEMENT, stored)
        == expected
    )
    assert to_source_credential_json(DocumentSource.JIRA, stored) == expected
    assert is_credential_usable_for_source(
        DocumentSource.JIRA, stored, DocumentSource.JIRA_SERVICE_MANAGEMENT
    )


def test_jsm_refuses_confluence_oauth_credentials() -> None:
    stored = to_stored_credential_json(
        DocumentSource.CONFLUENCE, _CONFLUENCE_OAUTH_JSON, None
    )

    assert not is_credential_usable_for_source(
        DocumentSource.CONFLUENCE, stored, DocumentSource.JIRA_SERVICE_MANAGEMENT
    )
    with pytest.raises(ValueError, match="cannot be used"):
        to_source_credential_json(DocumentSource.JIRA_SERVICE_MANAGEMENT, stored)


def test_existing_source_shaped_credential_keeps_its_shape() -> None:
    refreshed = {**_CONFLUENCE_JSON, "confluence_access_token": "new-token"}

    stored = to_stored_credential_json(
        DocumentSource.CONFLUENCE, refreshed, _CONFLUENCE_JSON
    )

    assert stored == refreshed
    assert to_source_credential_json(DocumentSource.CONFLUENCE, stored) == refreshed
    assert not is_credential_usable_for_source(
        DocumentSource.CONFLUENCE, stored, DocumentSource.JIRA
    )


def test_write_back_to_a_family_credential_keeps_the_family_shape() -> None:
    stored = to_stored_credential_json(
        DocumentSource.CONFLUENCE, _CONFLUENCE_JSON, None
    )

    rewritten = to_stored_credential_json(
        DocumentSource.JIRA,
        {"jira_user_email": "user@example.com", "jira_api_token": "new-token"},
        stored,
    )

    assert rewritten == {**stored, "token": "new-token"}


def test_source_outside_the_family_cannot_read_or_write_it() -> None:
    stored = to_stored_credential_json(
        DocumentSource.CONFLUENCE, _CONFLUENCE_JSON, None
    )

    with pytest.raises(ValueError):
        to_source_credential_json(DocumentSource.SLACK, stored)
    with pytest.raises(ValueError):
        to_stored_credential_json(
            DocumentSource.SLACK, {"slack_bot_token": "x"}, stored
        )
    assert not is_credential_usable_for_source(
        DocumentSource.CONFLUENCE, stored, DocumentSource.SLACK
    )


def test_family_marker_is_reserved() -> None:
    with pytest.raises(ValueError):
        to_stored_credential_json(
            DocumentSource.SLACK, {CREDENTIAL_FAMILY_KEY: "atlassian"}, None
        )


def test_keys_of_another_family_source_are_rejected() -> None:
    with pytest.raises(ValueError, match="jira_api_token"):
        to_stored_credential_json(
            DocumentSource.CONFLUENCE,
            {**_CONFLUENCE_JSON, "jira_api_token": "secret-jira-token"},
            None,
        )


_CONFLUENCE_OAUTH_JSON: dict[str, Any] = {
    "confluence_username": None,
    "confluence_access_token": "access",
    "confluence_refresh_token": "refresh",
    "created_at": "2026-09-28T00:00:00+00:00",
    "expires_in": 3600,
    "cloud_id": "cloud",
    "wiki_base": "https://acme.atlassian.net",
}


def test_confluence_oauth_credential_round_trips() -> None:
    stored = to_stored_credential_json(
        DocumentSource.CONFLUENCE, _CONFLUENCE_OAUTH_JSON, None
    )

    assert (
        to_source_credential_json(DocumentSource.CONFLUENCE, stored)
        == _CONFLUENCE_OAUTH_JSON
    )


def test_jira_data_center_credential_has_no_email_key() -> None:
    stored = to_stored_credential_json(
        DocumentSource.JIRA, {"jira_user_email": "", "jira_api_token": "pat"}, None
    )

    # The Jira client treats a present email key as Atlassian Cloud.
    assert to_source_credential_json(DocumentSource.JIRA, stored) == {
        "jira_api_token": "pat"
    }
    assert to_source_credential_json(DocumentSource.CONFLUENCE, stored) == {
        "confluence_username": None,
        "confluence_access_token": "pat",
    }


def test_invalid_family_source_credential_is_rejected_without_its_values() -> None:
    with pytest.raises(ValueError) as exc_info:
        to_stored_credential_json(
            DocumentSource.JIRA, {"jira_user_email": "secret@example.com"}, None
        )

    assert "jira_api_token" in str(exc_info.value)
    assert "secret@example.com" not in str(exc_info.value)


def test_jira_refuses_a_confluence_oauth_credential() -> None:
    """Jira cannot use or refresh a Confluence Cloud OAuth (3LO) token."""
    stored = to_stored_credential_json(
        DocumentSource.CONFLUENCE, _CONFLUENCE_OAUTH_JSON, None
    )

    assert not is_credential_usable_for_source(
        DocumentSource.CONFLUENCE, stored, DocumentSource.JIRA
    )
    with pytest.raises(ValueError, match="cannot be used by the jira source"):
        to_source_credential_json(DocumentSource.JIRA, stored)
    # A Jira write would rebuild the credential without its OAuth state.
    with pytest.raises(ValueError, match="cannot write this"):
        to_stored_credential_json(
            DocumentSource.JIRA, {"jira_api_token": "new"}, stored
        )


def test_malformed_family_credential_is_not_usable_by_other_sources() -> None:
    stored = {"email": "user@example.com", CREDENTIAL_FAMILY_KEY: "atlassian"}

    assert not is_credential_usable_for_source(
        DocumentSource.CONFLUENCE, stored, DocumentSource.JIRA
    )


def test_gmail_service_account_credential_is_usable_by_google_drive() -> None:
    gmail_json = {
        "google_service_account_key": '{"type": "service_account"}',
        "google_primary_admin": "admin@example.com",
        "authentication_method": "uploaded",
    }

    stored = to_stored_credential_json(DocumentSource.GMAIL, gmail_json, None)

    # Absent keys stay absent: the Google auth helpers branch on key presence.
    assert to_source_credential_json(DocumentSource.GOOGLE_DRIVE, stored) == gmail_json
    assert is_credential_usable_for_source(
        DocumentSource.GMAIL, stored, DocumentSource.GOOGLE_DRIVE
    )


def test_unknown_google_credential_keys_are_kept() -> None:
    source_json = {"client_id": "id", "client_secret": "secret"}

    stored = to_stored_credential_json(DocumentSource.GMAIL, source_json, None)

    assert to_source_credential_json(DocumentSource.GOOGLE_DRIVE, stored) == (
        source_json
    )


def test_google_app_credential_json_string_is_accepted() -> None:
    app_credential = '{"web": {"client_id": "id"}}'
    source_json = {"google_app_credential": app_credential}

    stored = to_stored_credential_json(DocumentSource.GMAIL, source_json, None)

    assert to_source_credential_json(DocumentSource.GOOGLE_DRIVE, stored) == (
        source_json
    )


def test_sharepoint_certificate_credential_maps_to_each_microsoft_source() -> None:
    sharepoint_json = {
        "authentication_method": "certificate",
        "sp_client_id": "client",
        "sp_directory_id": "tenant",
        "sp_private_key": "pfx-base64",
        "sp_certificate_password": "password",
    }

    stored = to_stored_credential_json(DocumentSource.SHAREPOINT, sharepoint_json, None)

    assert to_source_credential_json(DocumentSource.TEAMS, stored) == {
        "authentication_method": "certificate",
        "teams_client_id": "client",
        "teams_directory_id": "tenant",
        "teams_private_key": "pfx-base64",
        "teams_certificate_password": "password",
    }
    assert (
        to_source_credential_json(DocumentSource.SHAREPOINT, stored) == sharepoint_json
    )


def test_onedrive_prefixed_authentication_method_is_read() -> None:
    stored = to_stored_credential_json(
        DocumentSource.ONEDRIVE,
        {
            "onedrive_client_id": "client",
            "onedrive_directory_id": "tenant",
            "onedrive_client_secret": "secret",
            "onedrive_authentication_method": "client_secret",
        },
        None,
    )

    assert to_source_credential_json(DocumentSource.OUTLOOK, stored) == {
        "outlook_client_id": "client",
        "outlook_directory_id": "tenant",
        "outlook_client_secret": "secret",
        "authentication_method": "client_secret",
    }


def test_keys_of_another_microsoft_source_are_rejected() -> None:
    with pytest.raises(ValueError, match="teams_client_id"):
        to_stored_credential_json(
            DocumentSource.SHAREPOINT,
            {
                "sp_client_id": "client",
                "sp_directory_id": "tenant",
                "teams_client_id": "other-client",
            },
            None,
        )
