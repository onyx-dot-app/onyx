"""A fake Atlassian family (Confluence and Jira) for credential-family tests.

No family is registered in production yet, so tests register this one with
``monkeypatch`` and it is removed after each test.
"""

from typing import Any

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.credential_families import FAMILY_CREDENTIAL_CODECS
from onyx.connectors.credential_family_base import (
    CredentialFamily,
    FamilyCredential,
    FamilyCredentialCodec,
)


class FakeAtlassianCredential(FamilyCredential):
    email: str | None = None
    token: str


class _FakeConfluenceCodec(FamilyCredentialCodec[FakeAtlassianCredential]):
    family = CredentialFamily.ATLASSIAN
    family_model = FakeAtlassianCredential

    def to_family(self, source_json: dict[str, Any]) -> FakeAtlassianCredential:
        return FakeAtlassianCredential(
            email=source_json.get("confluence_username"),
            token=source_json["confluence_access_token"],
        )

    def from_family(self, family_credential: FakeAtlassianCredential) -> dict[str, Any]:
        return {
            "confluence_username": family_credential.email,
            "confluence_access_token": family_credential.token,
        }


class _FakeJiraCodec(FamilyCredentialCodec[FakeAtlassianCredential]):
    family = CredentialFamily.ATLASSIAN
    family_model = FakeAtlassianCredential

    def to_family(self, source_json: dict[str, Any]) -> FakeAtlassianCredential:
        return FakeAtlassianCredential(
            email=source_json.get("jira_user_email"),
            token=source_json["jira_api_token"],
        )

    def from_family(self, family_credential: FakeAtlassianCredential) -> dict[str, Any]:
        return {
            "jira_user_email": family_credential.email,
            "jira_api_token": family_credential.token,
        }


def register_fake_atlassian_family(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        FAMILY_CREDENTIAL_CODECS, DocumentSource.CONFLUENCE, _FakeConfluenceCodec()
    )
    monkeypatch.setitem(FAMILY_CREDENTIAL_CODECS, DocumentSource.JIRA, _FakeJiraCodec())
