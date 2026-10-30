from typing import Annotated

from onyx.configs.app_configs import INDEX_BATCH_SIZE, JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeExclude,
    ScopeInclude,
)
from onyx.connectors.jira.config import JiraCredentialBinding


class JiraServiceManagementConnectorConfig(JiraCredentialBinding, ConnectorConfig):
    """JSM scope: service desks, or one Jira project key.

    The credential and site fields are the Jira ones, because a JSM project is
    read with the same Atlassian account and site URL.
    """

    service_desk_ids: Annotated[
        list[str] | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True)),
    ] = None
    project_key: Annotated[
        str | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True)),
    ] = None
    comment_email_blacklist: Annotated[
        list[str] | None, FieldPolicy(FieldClass.BEHAVIOR)
    ] = None
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
    labels_to_skip: Annotated[
        list[str], FieldPolicy(FieldClass.SCOPE, scope=ScopeExclude())
    ] = JIRA_CONNECTOR_LABELS_TO_SKIP
