from typing import Annotated, Any

from pydantic import field_validator

from onyx.connectors.connector_config import ConnectorConfig, RealmCredentialBinding
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeInclude,
    ScopeOpaque,
    ScopeToggle,
)

_DOCUMENT_TYPE_TOGGLE = FieldPolicy(
    FieldClass.SCOPE, scope=ScopeToggle(widens_when=True)
)


class GithubCredentialBinding(RealmCredentialBinding):
    REALM_KEY = "github_base_url"
    DEFAULT_REALM = "https://github.com"

    # Where the account works. The connector reads it from the credential.
    github_base_url: Annotated[str | None, FieldPolicy(FieldClass.COSMETIC)] = None


class GithubConnectorConfig(GithubCredentialBinding, ConnectorConfig):
    repo_owner: Annotated[str, FieldPolicy(FieldClass.IDENTITY)]
    repositories: Annotated[
        str | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True)),
    ] = None
    state_filter: Annotated[str, FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque())] = (
        "all"
    )
    include_prs: Annotated[bool, _DOCUMENT_TYPE_TOGGLE] = True
    include_issues: Annotated[bool, _DOCUMENT_TYPE_TOGGLE] = False
    include_files: Annotated[bool, _DOCUMENT_TYPE_TOGGLE] = False
    # File document ids contain the branch.
    branch: Annotated[str | None, FieldPolicy(FieldClass.IDENTITY)] = None

    # A blank value means every repository or the default branch, as in the
    # connector.
    @field_validator("repositories", "branch", mode="before")
    @classmethod
    def _strip_blank_to_none(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        return value.strip() or None
