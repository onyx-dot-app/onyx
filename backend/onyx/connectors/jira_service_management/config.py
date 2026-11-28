from typing import Annotated

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import FieldClass, FieldPolicy, ScopeInclude


class JiraServiceManagementConnectorConfig(ConnectorConfig):
    """Configuration for the Jira Service Management connector."""

    base_url: Annotated[str | None, FieldPolicy(FieldClass.IDENTITY)] = None
    project_key: Annotated[
        str | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True)),
    ] = None
    service_desk_id: Annotated[
        str | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True)),
    ] = None
    include_internal_comments: Annotated[
        bool, FieldPolicy(FieldClass.BEHAVIOR)
    ] = False
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
