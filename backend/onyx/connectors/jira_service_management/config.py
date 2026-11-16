from typing import Annotated

from pydantic import field_validator

from onyx.configs.app_configs import INDEX_BATCH_SIZE, JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.connectors.connector_config import ConnectorConfig, field_format_error
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeExclude,
    ScopeInclude,
)
from onyx.connectors.jira.config import JiraCredentialBinding

PROJECT_KEY_REQUIRED_ERROR = "A Jira Service Management project key is required."


class JiraServiceManagementConnectorConfig(JiraCredentialBinding, ConnectorConfig):
    # The service project whose requests are indexed.
    project_key: Annotated[
        str, FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=False))
    ]
    # Drops these authors' comments from the request text.
    comment_email_blacklist: Annotated[
        list[str] | None, FieldPolicy(FieldClass.BEHAVIOR)
    ] = None
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
    labels_to_skip: Annotated[
        list[str], FieldPolicy(FieldClass.SCOPE, scope=ScopeExclude())
    ] = JIRA_CONNECTOR_LABELS_TO_SKIP

    @field_validator("project_key")
    @classmethod
    def _project_key_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise field_format_error(PROJECT_KEY_REQUIRED_ERROR)
        return stripped
