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


def test_confluence_oauth_credential_round_trips() -> None:
    oauth_json = {
        "confluence_username": None,
        "confluence_access_token": "access",
        "confluence_refresh_token": "refresh",
        "created_at": "2026-09-28T00:00:00+00:00",
        "expires_in": 3600,
        "cloud_id": "cloud",
        "wiki_base": "https://acme.atlassian.net",
    }

    stored = to_stored_credential_json(DocumentSource.CONFLUENCE, oauth_json, None)

    assert to_source_credential_json(DocumentSource.CONFLUENCE, stored) == oauth_json


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
