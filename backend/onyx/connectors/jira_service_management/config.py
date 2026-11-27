from typing import Annotated

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
from onyx.connectors.planning_rule import ConnectorChangeOverride

_PROJECT_KEY = "project_key"
_SERVICE_DESK_ID = "service_desk_id"
_JQL_QUERY = "jql_query"

JQL_ORDER_BY_ERROR = (
    "Unsupported clause: ORDER BY. Jira Service Management does not allow it inside the sync filter."
)


class JiraServiceManagementCredentialBinding(CredentialBinding):
    # Document ids are issue URLs on this base URL.
    jira_base_url: Annotated[str, FieldPolicy(FieldClass.IDENTITY)]
    # Only selects the API gateway: document ids keep jira_base_url.
    scoped_token: Annotated[bool, FieldPolicy(FieldClass.COSMETIC)] = False


class JiraServiceManagementConnectorConfig(
    JiraServiceManagementCredentialBinding, ConnectorConfig
):
    # jql_query takes precedence over the project and service desk scope.
    project_key: Annotated[
        str | None,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=True),
            depends_on=(_JQL_QUERY,),
        ),
    ] = None
    service_desk_id: Annotated[
        str | None,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=True),
            depends_on=(_JQL_QUERY,),
        ),
    ] = None
    jql_query: Annotated[
        str | None, FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque())
    ] = None
    # Drops these authors' comments from the request / ticket text.
    comment_email_blacklist: Annotated[
        list[str] | None, FieldPolicy(FieldClass.BEHAVIOR)
    ] = None
    labels_to_skip: Annotated[
        list[str], FieldPolicy(FieldClass.SCOPE, scope=ScopeExclude())
    ] = JIRA_CONNECTOR_LABELS_TO_SKIP
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE

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
    # The connector ignores project/service desk scope while a JQL query is set.
    if old.jql_query and new.jql_query:
        return ConnectorChangeOverride(
            scope_directions={
                _PROJECT_KEY: ScopeDirection.NONE,
                _SERVICE_DESK_ID: ScopeDirection.NONE,
            }
        )
    return None
