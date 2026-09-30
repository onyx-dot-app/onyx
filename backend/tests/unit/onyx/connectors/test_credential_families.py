from typing import Any

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.credential_families import (
    is_credential_usable_for_source,
    to_source_credential_json,
    to_stored_credential_json,
)
from onyx.connectors.credential_family_base import CREDENTIAL_FAMILY_KEY
from tests.utils.fake_credential_family import register_fake_atlassian_family

_CONFLUENCE_JSON: dict[str, Any] = {
    "confluence_username": "user@example.com",
    "confluence_access_token": "token",
}


@pytest.fixture(autouse=True)
def fake_atlassian_family(monkeypatch: pytest.MonkeyPatch) -> None:
    register_fake_atlassian_family(monkeypatch)


def test_new_family_credential_is_stored_in_the_family_shape() -> None:
    stored = to_stored_credential_json(
        DocumentSource.CONFLUENCE, _CONFLUENCE_JSON, None
    )

    assert stored == {
        "email": "user@example.com",
        "token": "token",
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


def test_codec_can_refuse_a_family_credential() -> None:
    stored = to_stored_credential_json(
        DocumentSource.CONFLUENCE, {"confluence_access_token": "token"}, None
    )

    assert is_credential_usable_for_source(
        DocumentSource.CONFLUENCE, stored, DocumentSource.CONFLUENCE
    )
    assert not is_credential_usable_for_source(
        DocumentSource.CONFLUENCE, stored, DocumentSource.JIRA
    )
    with pytest.raises(ValueError, match="cannot be used by the jira source"):
        to_source_credential_json(DocumentSource.JIRA, stored)
    # A write would rebuild the credential without what Jira cannot read.
    with pytest.raises(ValueError, match="cannot write this"):
        to_stored_credential_json(
            DocumentSource.JIRA, {"jira_api_token": "new"}, stored
        )


def test_malformed_family_credential_is_not_usable_by_other_sources() -> None:
    stored = {"email": "user@example.com", CREDENTIAL_FAMILY_KEY: "atlassian"}

    assert not is_credential_usable_for_source(
        DocumentSource.CONFLUENCE, stored, DocumentSource.JIRA
    )
