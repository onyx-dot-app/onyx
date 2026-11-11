import re

from pydantic import field_validator

from onyx.connectors.connector_config import field_format_error
from onyx.connectors.jira.config import JiraConnectorConfig, jira_planning_rule
from onyx.connectors.planning_rule import ConnectorChangeOverride

# Jira project keys are uppercase. Digits and underscores are allowed after
# the first letter. Reject anything else so a key cannot break out of the
# quoted JQL project clause.
PROJECT_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

PROJECT_KEY_ERROR = (
    "Project key must start with a letter and contain only letters, numbers, "
    "and underscores."
)
BLANK_PROJECT_KEY_ERROR = "Project key cannot be blank."
BLANK_JQL_ERROR = "JQL query cannot be blank."


class JiraServiceManagementConnectorConfig(JiraConnectorConfig):
    """Same account and scope fields as Jira. A project key, when set, must be
    a service desk project. The connector checks that at validation time."""

    @field_validator("project_key")
    @classmethod
    def _project_key_shape(cls, value: str | None) -> str | None:
        """Reject a blank or unsafe project key. ``None`` means every desk."""
        if value is None:
            return None
        key = value.strip().upper()
        if not key:
            raise field_format_error(BLANK_PROJECT_KEY_ERROR)
        if PROJECT_KEY_RE.fullmatch(key) is None:
            raise field_format_error(PROJECT_KEY_ERROR)
        return key

    @field_validator("jql_query")
    @classmethod
    def _jql_not_blank(cls, value: str | None) -> str | None:
        """Reject a blank JQL query. ``None`` means the query is not the scope."""
        if value is None:
            return None
        query = value.strip()
        if not query:
            raise field_format_error(BLANK_JQL_ERROR)
        return query


def jira_service_management_planning_rule(
    old: JiraServiceManagementConnectorConfig,
    new: JiraServiceManagementConnectorConfig,
) -> ConnectorChangeOverride | None:
    """A JQL query still replaces the project key, as it does for Jira."""
    return jira_planning_rule(old, new)
