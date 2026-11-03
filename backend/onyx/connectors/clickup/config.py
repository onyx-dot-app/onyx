from enum import StrEnum
from typing import Annotated, Any

from pydantic import field_validator

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeDirection,
    ScopeInclude,
    ScopeOpaque,
)
from onyx.connectors.planning_rule import ConnectorChangeOverride

_CONNECTOR_IDS = "connector_ids"


class ClickupConnectorType(StrEnum):
    LIST = "list"
    FOLDER = "folder"
    SPACE = "space"
    WORKSPACE = "workspace"


class ClickupConnectorConfig(ConnectorConfig):
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
    # Picks the kind of container that connector_ids names.
    connector_type: Annotated[
        ClickupConnectorType | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque()),
    ] = None
    # Empty sends no container filter, so the whole workspace is fetched.
    connector_ids: Annotated[
        list[str] | None,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=True),
            depends_on=("connector_type",),
        ),
    ] = None
    retrieve_task_comments: Annotated[bool, FieldPolicy(FieldClass.BEHAVIOR)] = True

    # The constructor treats "" like None (a workspace connector).
    @field_validator("connector_type", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        return None if value == "" else value


def _is_workspace_mode(config: ClickupConnectorConfig) -> bool:
    return config.connector_type in (None, ClickupConnectorType.WORKSPACE)


def clickup_planning_rule(
    old: ClickupConnectorConfig, new: ClickupConnectorConfig
) -> ConnectorChangeOverride | None:
    # A workspace connector sends no container filter.
    if _is_workspace_mode(old) and _is_workspace_mode(new):
        return ConnectorChangeOverride(
            scope_directions={_CONNECTOR_IDS: ScopeDirection.NONE}
        )
    return None
