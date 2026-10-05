from typing import Annotated

from onyx.configs.app_configs import CONTINUE_ON_CONNECTOR_FAILURE, INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import FieldClass, FieldPolicy, ScopeInclude

_COSMETIC = FieldPolicy(FieldClass.COSMETIC)


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
