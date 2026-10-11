from typing import Annotated

from onyx.connectors.connector_config import CredentialBinding
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeDirection,
)
from onyx.connectors.jira.config import JiraConnectorConfig
from onyx.connectors.planning_rule import ConnectorChangeOverride

_PROJECT_KEY = "project_key"


class JiraServiceManagementCredentialBinding(CredentialBinding):
    # Document ids are issue URLs on this base URL.
    jira_base_url: Annotated[str, FieldPolicy(FieldClass.IDENTITY)]
    # Only selects the API gateway: document ids keep jira_base_url.
    scoped_token: Annotated[bool, FieldPolicy(FieldClass.COSMETIC)] = False


class JiraServiceManagementConnectorConfig(
    JiraServiceManagementCredentialBinding, JiraConnectorConfig
):
    """Connector-scope config for a Jira Service Management project.

    Fields mirror ``JiraConnectorConfig``: a JSM project is a Jira project,
    scoped the same way. The credential gate is JSM-specific, so this gets a
    dedicated binding (same shape as Jira's) rather than inheriting Jira's.
    """


def jira_service_management_planning_rule(
    old: JiraServiceManagementConnectorConfig,
    new: JiraServiceManagementConnectorConfig,
) -> ConnectorChangeOverride | None:
    # The connector ignores the project key while a JQL query is set.
    if old.jql_query and new.jql_query:
        return ConnectorChangeOverride(
            scope_directions={_PROJECT_KEY: ScopeDirection.NONE}
        )
    return None
