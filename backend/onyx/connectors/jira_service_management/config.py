"""Configuration for the Jira Service Management connector.

The connector intentionally reuses every Jira scope and behavior field: a JSM
project is a regular Jira project of type ``service_desk``, so project keys,
JQL, label skipping and the comment blacklist all apply unchanged.
"""

from onyx.connectors.field_policy import ScopeDirection
from onyx.connectors.jira.config import JiraConnectorConfig, jira_planning_rule
from onyx.connectors.planning_rule import ConnectorChangeOverride

_PROJECT_KEY = "project_key"


class JiraServiceManagementConnectorConfig(JiraConnectorConfig):
    """Same fields as Jira; registered separately so the source keeps its own
    document type, icon and credential family binding."""


def jira_service_management_planning_rule(
    old: JiraServiceManagementConnectorConfig,
    new: JiraServiceManagementConnectorConfig,
) -> ConnectorChangeOverride | None:
    """Planning rule for Jira Service Management connector config edits.

    Under the default Everything scope (neither ``project_key`` nor
    ``jql_query`` set), the JSM connector drops issues from non-``service_desk``
    projects. Setting or clearing ``project_key`` while ``jql_query`` stays
    unset swaps between that filtered Everything set and an unfiltered
    project set, so non-``service_desk`` tickets in ``project_key`` enter or
    leave scope while other ``service_desk`` projects do the opposite.
    """
    old_jql = (old.jql_query or "").strip()
    new_jql = (new.jql_query or "").strip()
    if old_jql and new_jql:
        return jira_planning_rule(old, new)
    if old_jql or new_jql:
        return None

    old_project = (old.project_key or "").strip()
    new_project = (new.project_key or "").strip()
    if bool(old_project) != bool(new_project):
        return ConnectorChangeOverride(
            scope_directions={_PROJECT_KEY: ScopeDirection.BOTH}
        )
    return None
