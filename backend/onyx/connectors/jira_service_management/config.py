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


class JiraServiceManagementConnectorConfig(JiraCredentialBinding, ConnectorConfig):
    # Key of the Jira Service Management project to index.
    project_key: Annotated[
        str,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=False, split_on_commas=False),
        ),
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
    def _project_key_is_set(cls, value: str) -> str:
        key: str = value.strip()
        if not key:
            raise field_format_error(
                "Enter the key of a Jira Service Management project."
            )
        return key
