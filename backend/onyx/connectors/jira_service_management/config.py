from typing import Annotated

from onyx.configs.app_configs import INDEX_BATCH_SIZE, JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.connectors.connector_config import ConnectorConfig, CredentialBinding
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
_SERVICE_DESK_IDS = "service_desk_ids"
_QUEUE_IDS = "queue_ids"
_REQUEST_TYPES = "request_types"


class JiraServiceManagementCredentialBinding(CredentialBinding):
    # Document ids are request/issue URLs on this base URL.
    jira_service_management_base_url: Annotated[str, FieldPolicy(FieldClass.IDENTITY)]
    # Only selects the API gateway: document ids keep jira_service_management_base_url.
    scoped_token: Annotated[bool, FieldPolicy(FieldClass.COSMETIC)] = False


class JiraServiceManagementConnectorConfig(
    JiraServiceManagementCredentialBinding, ConnectorConfig
):
    # jql_query takes precedence over project_key / service_desk_ids / queue_ids / request_types.
    project_key: Annotated[
        str | None,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=True),
            depends_on=("jql_query",),
        ),
    ] = None
    service_desk_ids: Annotated[
        list[str] | None,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=True),
            depends_on=("jql_query",),
        ),
    ] = None
    queue_ids: Annotated[
        list[str] | None,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=True),
            depends_on=("jql_query",),
        ),
    ] = None
    request_types: Annotated[
        list[str] | None,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=True),
            depends_on=("jql_query",),
        ),
    ] = None
    jql_query: Annotated[
        str | None, FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque())
    ] = None
    # Drops these authors' comments from the request text.
    comment_email_blacklist: Annotated[
        list[str] | None, FieldPolicy(FieldClass.BEHAVIOR)
    ] = None
    labels_to_skip: Annotated[
        list[str], FieldPolicy(FieldClass.SCOPE, scope=ScopeExclude())
    ] = JIRA_CONNECTOR_LABELS_TO_SKIP
    include_internal_comments: Annotated[bool, FieldPolicy(FieldClass.BEHAVIOR)] = True
    include_sla: Annotated[bool, FieldPolicy(FieldClass.BEHAVIOR)] = True
    include_changelog: Annotated[bool, FieldPolicy(FieldClass.BEHAVIOR)] = True
    include_attachments: Annotated[bool, FieldPolicy(FieldClass.BEHAVIOR)] = False
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE


def jira_service_management_planning_rule(
    old: JiraServiceManagementConnectorConfig,
    new: JiraServiceManagementConnectorConfig,
) -> ConnectorChangeOverride | None:
    # The connector ignores project/desk/queue/request_type scope while a JQL query is set.
    if old.jql_query and new.jql_query:
        return ConnectorChangeOverride(
            scope_directions={
                _PROJECT_KEY: ScopeDirection.NONE,
                _SERVICE_DESK_IDS: ScopeDirection.NONE,
                _QUEUE_IDS: ScopeDirection.NONE,
                _REQUEST_TYPES: ScopeDirection.NONE,
            }
        )
    return None
