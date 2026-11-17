from typing import Annotated

from onyx.configs.app_configs import INDEX_BATCH_SIZE, JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeExclude,
    ScopeOpaque,
)
from onyx.connectors.jira.config import JiraCredentialBinding


class JiraServiceManagementConnectorConfig(JiraCredentialBinding, ConnectorConfig):
    # The Jira Service Management project (service desk) whose tickets are
    # indexed. Required: the connector always pulls one specified project.
    project_key: Annotated[str, FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque())]
    # Internal (agent-only) comments stay out of the indexed text unless set.
    include_internal_comments: Annotated[bool, FieldPolicy(FieldClass.BEHAVIOR)] = (
        False
    )
    # Drops these authors' comments from the ticket text.
    comment_email_blacklist: Annotated[
        list[str] | None, FieldPolicy(FieldClass.BEHAVIOR)
    ] = None
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
    labels_to_skip: Annotated[
        list[str], FieldPolicy(FieldClass.SCOPE, scope=ScopeExclude())
    ] = JIRA_CONNECTOR_LABELS_TO_SKIP
