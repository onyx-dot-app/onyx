import re
from typing import Annotated

from pydantic import field_validator

from onyx.configs.app_configs import INDEX_BATCH_SIZE, JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.connectors.atlassian_query import has_order_by
from onyx.connectors.connector_config import field_format_error
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeDirection,
    ScopeExclude,
    ScopeInclude,
    ScopeOpaque,
)
from onyx.connectors.jira.config import JiraConnectorConfig
from onyx.connectors.planning_rule import ConnectorChangeOverride

_JQL_QUERY = "jql_query"
_PROJECT_KEY = "project_key"

JQL_ORDER_BY_ERROR = (
    "Unsupported clause: ORDER BY. Jira does not allow it inside the sync filter."
)

# A Jira project key starts with an upper-case letter and holds upper-case
# letters, digits and underscores. The ``fullmatch`` call below anchors the
# whole value, so a trailing newline is rejected too.
_PROJECT_KEY_PATTERN = r"[A-Z][A-Z0-9_]*"
_PROJECT_KEY_FORMAT_ERROR = (
    "A Jira project key holds upper-case letters, digits and underscores, "
    "and starts with a letter (for example SUPPORT)."
)


class JiraServiceManagementConnectorConfig(JiraConnectorConfig):
    # The service desk project whose requests are indexed. A service desk is a
    # Jira project type, so the key is a Jira project key.
    project_key: Annotated[
        str,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=False)),
    ]
    # Adds the service desk name, the request type and the portal URL of each
    # request to its text and metadata. The servicedeskapi calls that supply
    # them need a Service Desk agent licence.
    include_service_desk_metadata: Annotated[bool, FieldPolicy(FieldClass.BEHAVIOR)] = (
        True
    )
    # Drops these authors' comments from the request text.
    comment_email_blacklist: Annotated[
        list[str] | None, FieldPolicy(FieldClass.BEHAVIOR)
    ] = None
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
    labels_to_skip: Annotated[
        list[str], FieldPolicy(FieldClass.SCOPE, scope=ScopeExclude())
    ] = JIRA_CONNECTOR_LABELS_TO_SKIP
    # Narrows the requests further. A JSM request is a Jira issue, so this is a
    # JQL filter. Each sync wraps it in parentheses with a time filter.
    jql_query: Annotated[
        str | None, FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque())
    ] = None

    @field_validator(_PROJECT_KEY)
    @classmethod
    def _project_key_is_a_key(cls, value: str) -> str:
        if not re.fullmatch(_PROJECT_KEY_PATTERN, value):
            raise field_format_error(_PROJECT_KEY_FORMAT_ERROR)
        return value

    # Jira rejects ORDER BY inside the parentheses each sync wraps the query in.
    @field_validator(_JQL_QUERY)
    @classmethod
    def _jql_has_no_order_by(cls, value: str | None) -> str | None:
        if value is not None and has_order_by(value):
            raise field_format_error(JQL_ORDER_BY_ERROR)
        return value


def jsm_planning_rule(
    old: JiraServiceManagementConnectorConfig,
    new: JiraServiceManagementConnectorConfig,
) -> ConnectorChangeOverride | None:
    """A changed project key or JQL selects different requests.

    A different project key, or adding/removing a JQL filter, both drops the
    old requests and adds new ones, so the direction is BOTH. Saying that here
    keeps the plan explicit for the one connector that is always single-project.
    """
    directions: dict[str, ScopeDirection] = {}
    if old.project_key != new.project_key:
        directions[_PROJECT_KEY] = ScopeDirection.BOTH
    if old.jql_query != new.jql_query:
        directions[_JQL_QUERY] = ScopeDirection.BOTH
    return ConnectorChangeOverride(scope_directions=directions) if directions else None
