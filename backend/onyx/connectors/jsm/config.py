from typing import Annotated

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig, CredentialBinding
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeInclude,
    ScopeOpaque,
)


class JiraServiceManagementConnectorBinding(CredentialBinding):
    # Document ids are issue URLs on this base URL (same as the Jira
    # connector's jira_base_url).
    jsm_base_url: Annotated[str, FieldPolicy(FieldClass.IDENTITY)]


class JiraServiceManagementConnectorConfig(
    JiraServiceManagementConnectorBinding, ConnectorConfig
):
    # One desk: a single-item include scope (no comma splitting), with the
    # empty value meaning "every desk the credential can see".
    service_desk_id: Annotated[
        str | None,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=True, split_on_commas=False),
        ),
    ] = None
    # An opaque scope: the change direction of a JQL edit cannot be derived.
    jql_query: Annotated[
        str | None, FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque())
    ] = None
    # Only selects the fetch size: document ids and scope are untouched.
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
