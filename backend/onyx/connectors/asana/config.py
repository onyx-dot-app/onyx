from typing import Annotated

from onyx.configs.app_configs import CONTINUE_ON_CONNECTOR_FAILURE, INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeDirection,
    ScopeInclude,
)
from onyx.connectors.planning_rule import ConnectorChangeOverride

_COSMETIC = FieldPolicy(FieldClass.COSMETIC)
_ASANA_TEAM_ID = "asana_team_id"


class AsanaConnectorConfig(ConnectorConfig):
    # Task gids are global, so a new workspace swaps the fetched set (both).
    asana_workspace_id: Annotated[
        str,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=False)),
    ]
    asana_project_ids: Annotated[
        str | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True)),
    ] = None
    # Skips private projects of other teams, only when no project ids are set.
    asana_team_id: Annotated[
        str | None,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=True),
            depends_on=("asana_project_ids",),
        ),
    ] = None
    batch_size: Annotated[int, _COSMETIC] = INDEX_BATCH_SIZE
    continue_on_failure: Annotated[bool, _COSMETIC] = CONTINUE_ON_CONNECTOR_FAILURE


def _has_project_ids(config: AsanaConnectorConfig) -> bool:
    return any(
        project_id.strip() for project_id in (config.asana_project_ids or "").split(",")
    )


def asana_planning_rule(
    old: AsanaConnectorConfig, new: AsanaConnectorConfig
) -> ConnectorChangeOverride | None:
    # The team filter applies only when no project ids are set.
    if _has_project_ids(old) and _has_project_ids(new):
        return ConnectorChangeOverride(
            scope_directions={_ASANA_TEAM_ID: ScopeDirection.NONE}
        )
    return None
