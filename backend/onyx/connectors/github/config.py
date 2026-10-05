from typing import Annotated

from onyx.connectors.connector_config import ConnectorConfig
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


class GithubConnectorConfig(ConnectorConfig):
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
