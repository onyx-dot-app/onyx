from typing import Annotated, ClassVar

from pydantic import field_validator

from onyx.configs.app_configs import INDEX_BATCH_SIZE, JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.connectors.atlassian_query import has_order_by
from onyx.connectors.connector_config import (
    ConnectorConfig,
    CredentialBinding,
    field_format_error,
)
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeDirection,
    ScopeExclude,
    ScopeInclude,
    ScopeOpaque,
)
from onyx.connectors.jira.config import (
    JQL_ORDER_BY_ERROR,
    JiraCredentialBinding,
    _JQL_QUERY,
    _PROJECT_KEY,
)
from onyx.connectors.planning_rule import ConnectorChangeOverride

_SERVICE_DESK_ID = "service_desk_id"


class JiraServiceManagementConnectorConfig(JiraCredentialBinding, ConnectorConfig):
    """Configuration for Jira Service Management (JSM) connector.
    
    Indexes service desk requests, customer portal interactions, and status transitions
    from a specified Jira Service Management project.
    """

    # jql_query takes precedence over project_key if supplied
    project_key: Annotated[
        str | None,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=True),
            depends_on=(_JQL_QUERY,),
        ),
    ] = None

    # Optional service desk portal identifier
    service_desk_id: Annotated[
        str | None,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=True),
        ),
    ] = None

    # When True, indexes only customer-visible comments and skips internal agent whisper notes
    customer_visible_only: Annotated[
        bool,
        FieldPolicy(FieldClass.BEHAVIOR),
    ] = True

    # Drops comments by specified bot or system author email addresses
    comment_email_blacklist: Annotated[
        list[str] | None, FieldPolicy(FieldClass.BEHAVIOR)
    ] = None

    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE

    labels_to_skip: Annotated[
        list[str], FieldPolicy(FieldClass.SCOPE, scope=ScopeExclude())
    ] = JIRA_CONNECTOR_LABELS_TO_SKIP

    jql_query: Annotated[
        str | None, FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque())
    ] = None

    @field_validator(_JQL_QUERY)
    @classmethod
    def _jql_has_no_order_by(cls, value: str | None) -> str | None:
        if value is not None and has_order_by(value):
            raise field_format_error(JQL_ORDER_BY_ERROR)
        return value


def jsm_planning_rule(
    old: JiraServiceManagementConnectorConfig, new: JiraServiceManagementConnectorConfig
) -> ConnectorChangeOverride | None:
    if old.jql_query and new.jql_query:
        return ConnectorChangeOverride(
            scope_directions={_PROJECT_KEY: ScopeDirection.NONE}
        )
    return None
