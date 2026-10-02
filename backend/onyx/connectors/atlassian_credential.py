"""The Atlassian credential family: Confluence and Jira share one account."""

from typing import Any

from pydantic import BaseModel, ConfigDict

from onyx.connectors.credential_family_base import (
    CredentialFamily,
    FamilyCredential,
    FamilyCredentialCodec,
)
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    credential_uses_scoped_token,
)

_CONFLUENCE_USERNAME_KEY = "confluence_username"
_CONFLUENCE_ACCESS_TOKEN_KEY = "confluence_access_token"
_CONFLUENCE_REFRESH_TOKEN_KEY = "confluence_refresh_token"
_JIRA_USER_EMAIL_KEY = "jira_user_email"
_JIRA_API_TOKEN_KEY = "jira_api_token"
# Shared by both sources: whether the API token has scopes, which routes it
# through Atlassian's API gateway.
SCOPED_TOKEN_KEY = "scoped_token"


class AtlassianOAuth(BaseModel):
    """Confluence Cloud OAuth (3LO) token state. Field names match the keys the
    OAuth flow writes, except ``refresh_token``."""

    # Errors must not echo secret values.
    model_config = ConfigDict(hide_input_in_errors=True)

    refresh_token: str
    created_at: str | None = None
    expires_at: str | None = None
    expires_in: int | None = None
    scope: str | None = None
    # Set once the user picks a site in the OAuth finalize step.
    cloud_id: str | None = None
    cloud_name: str | None = None
    wiki_base: str | None = None


class AtlassianCredential(FamilyCredential):
    # The Confluence username or Jira user email. Jira treats a credential with
    # an email as Atlassian Cloud and one without as Data Center.
    email: str | None = None
    # An API token, a personal access token, or the OAuth access token.
    token: str
    # The API token has scopes, so calls go through Atlassian's API gateway.
    scoped_token: bool = False
    oauth: AtlassianOAuth | None = None


class ConfluenceCredentialCodec(FamilyCredentialCodec[AtlassianCredential]):
    family = CredentialFamily.ATLASSIAN
    family_model = AtlassianCredential

    def to_family(self, source_json: dict[str, Any]) -> AtlassianCredential:
        refresh_token = source_json.get(_CONFLUENCE_REFRESH_TOKEN_KEY)
        return AtlassianCredential(
            email=source_json.get(_CONFLUENCE_USERNAME_KEY) or None,
            token=source_json[_CONFLUENCE_ACCESS_TOKEN_KEY],
            scoped_token=credential_uses_scoped_token(source_json),
            oauth=(
                AtlassianOAuth.model_validate(
                    {**source_json, "refresh_token": refresh_token}
                )
                if refresh_token
                else None
            ),
        )

    def from_family(self, family_credential: AtlassianCredential) -> dict[str, Any]:
        # The connector reads the username even for a data center token.
        source_json: dict[str, Any] = {
            _CONFLUENCE_USERNAME_KEY: family_credential.email,
            _CONFLUENCE_ACCESS_TOKEN_KEY: family_credential.token,
        }
        # Only a scoped token carries the key; absent reads as unscoped.
        if family_credential.scoped_token:
            source_json[SCOPED_TOKEN_KEY] = True
        if family_credential.oauth is None:
            return source_json
        oauth = family_credential.oauth.model_dump(exclude_none=True)
        source_json[_CONFLUENCE_REFRESH_TOKEN_KEY] = oauth.pop("refresh_token")
        return {**source_json, **oauth}


class JiraCredentialCodec(FamilyCredentialCodec[AtlassianCredential]):
    family = CredentialFamily.ATLASSIAN
    family_model = AtlassianCredential

    def to_family(self, source_json: dict[str, Any]) -> AtlassianCredential:
        return AtlassianCredential(
            email=source_json.get(_JIRA_USER_EMAIL_KEY) or None,
            token=source_json[_JIRA_API_TOKEN_KEY],
            scoped_token=credential_uses_scoped_token(source_json),
        )

    def from_family(self, family_credential: AtlassianCredential) -> dict[str, Any]:
        # The Jira client picks Cloud vs. Data Center by whether the email key
        # is present, so leave it out when there is no email.
        source_json: dict[str, Any] = {_JIRA_API_TOKEN_KEY: family_credential.token}
        # Only a scoped token carries the key; absent reads as unscoped.
        if family_credential.scoped_token:
            source_json[SCOPED_TOKEN_KEY] = True
        if family_credential.email:
            source_json[_JIRA_USER_EMAIL_KEY] = family_credential.email
        return source_json

    def accepts(self, family_credential: AtlassianCredential) -> bool:
        # Jira cannot use or refresh a Confluence Cloud OAuth (3LO) token.
        return family_credential.oauth is None
