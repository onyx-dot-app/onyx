from typing import Annotated

from onyx.configs.app_configs import (
    GITLAB_CONNECTOR_INCLUDE_CODE_FILES,
    INDEX_BATCH_SIZE,
)
from onyx.connectors.connector_config import ConnectorConfig, RealmCredentialBinding
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeOpaque,
    ScopeToggle,
)

# Merge request and issue document ids are web URLs that contain the project path.
_PROJECT_PATH = FieldPolicy(FieldClass.IDENTITY)
_DOCUMENT_TYPE_TOGGLE = FieldPolicy(
    FieldClass.SCOPE, scope=ScopeToggle(widens_when=True)
)


class GitlabCredentialBinding(RealmCredentialBinding):
    REALM_KEY = "gitlab_url"

    # Where the account works. The connector reads it from the credential.
    gitlab_url: Annotated[str | None, FieldPolicy(FieldClass.COSMETIC)] = None


class GitlabConnectorConfig(GitlabCredentialBinding, ConnectorConfig):
    project_owner: Annotated[str, _PROJECT_PATH]
    project_name: Annotated[str, _PROJECT_PATH]
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
    state_filter: Annotated[str, FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque())] = (
        "all"
    )
    include_mrs: Annotated[bool, _DOCUMENT_TYPE_TOGGLE] = True
    include_issues: Annotated[bool, _DOCUMENT_TYPE_TOGGLE] = True
    include_code_files: Annotated[bool, _DOCUMENT_TYPE_TOGGLE] = (
        GITLAB_CONNECTOR_INCLUDE_CODE_FILES
    )
