from typing import Annotated

from pydantic import Field

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeInclude,
)


class JiraServiceManagementConnectorConfig(ConnectorConfig):
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
    service_desk_ids: Annotated[
        str | list[str] | None,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=True, empty_list_means_none=True),
        ),
    ] = None
    project_key: Annotated[
        str | None,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=True),
        ),
    ] = None
    include_internal_comments: Annotated[bool, FieldPolicy(FieldClass.BEHAVIOR)] = False
    max_active_sla_requests: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = Field(
        default=1000, ge=1, le=10000
    )
