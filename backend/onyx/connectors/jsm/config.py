"""Configuration for the Jira Service Management (JSM) connector.

A JSM project is backed by a Jira project, so the connector takes the same
credential-bound fields as the Jira connector (``jira_base_url`` and an optional
``scoped_token``) plus the project / JQL scope. It reuses the Jira credential
binding and planning rule so the create form and credential-use checks behave
identically to Jira.
"""

from onyx.configs.app_configs import (
    JIRA_CONNECTOR_LABELS_TO_SKIP,
    JIRA_CONNECTOR_MAX_TICKET_SIZE,
    JIRA_SLIM_PAGE_SIZE,
)
from onyx.connectors.jira.config import (
    JiraConnectorConfig,
    JiraCredentialBinding,
    jira_planning_rule as jira_planning_rule,
)
from onyx.connectors.planning_rule import ConnectorChangeOverride

__all__ = [
    "JsmConnectorConfig",
    "JsmCredentialBinding",
    "jsm_planning_rule",
    "JSM_CONNECTOR_LABELS_TO_SKIP",
    "JSM_CONNECTOR_MAX_TICKET_SIZE",
    "JSM_SLIM_PAGE_SIZE",
]

# JSM reuses the Jira tuning knobs: a service desk request is a Jira issue, so
# the same size cap, slim page size and default skip-labels apply.
JSM_CONNECTOR_LABELS_TO_SKIP = JIRA_CONNECTOR_LABELS_TO_SKIP
JSM_CONNECTOR_MAX_TICKET_SIZE = JIRA_CONNECTOR_MAX_TICKET_SIZE
JSM_SLIM_PAGE_SIZE = JIRA_SLIM_PAGE_SIZE


class JsmCredentialBinding(JiraCredentialBinding):
    """The credential-bound fields of a JSM connector.

    Identical to Jira's: the site URL the documents are linked from and the
    optional scoped-token flag that only selects the API gateway. Subclassed so
    the JSM config has its own identity while sharing Jira's validation.
    """


class JsmConnectorConfig(JsmCredentialBinding, JiraConnectorConfig):
    """The stored config of a JSM connector.

    Inherits the Jira scope fields (``project_key``, ``jql_query``,
    ``comment_email_blacklist``, ``labels_to_skip``, ``batch_size``) and the
    ORDER BY guard, so a JSM project is indexed exactly like a Jira project.
    """


def jsm_planning_rule(
    old: JsmConnectorConfig, new: JsmConnectorConfig
) -> ConnectorChangeOverride | None:
    """Reuse Jira's planning rule: the connector ignores the project key while a
    JQL query is set."""
    return jira_planning_rule(old, new)