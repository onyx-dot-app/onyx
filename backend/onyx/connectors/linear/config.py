from typing import Annotated, Any

from pydantic import field_validator

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import FieldClass, FieldPolicy, ScopeInclude


class LinearConnectorConfig(ConnectorConfig):
    # Team keys such as ENG. Empty indexes every team the token can see.
    team_keys: Annotated[
        list[str] | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True)),
    ] = None
    # Project names or URLs. Empty indexes every project, and issues with
    # none. With teams set too, an issue must match both.
    projects: Annotated[
        list[str] | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True)),
    ] = None
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE

    # The scope planner diffs these lists, so a stored entry must mean what the
    # connector reads: a blank entry would otherwise plan a backfill of nothing,
    # which the connector takes as every team.
    @field_validator("team_keys", mode="before")
    @classmethod
    def _normalize_team_keys(cls, value: Any) -> Any:
        if not _is_string_list(value):
            return value
        return [key.strip().upper() for key in value if key.strip()]

    @field_validator("projects", mode="before")
    @classmethod
    def _normalize_projects(cls, value: Any) -> Any:
        if not _is_string_list(value):
            return value
        return [entry.strip() for entry in value if entry.strip()]


def _is_string_list(value: Any) -> bool:
    """Anything else is left for pydantic to reject with a field error."""
    return isinstance(value, list) and all(isinstance(item, str) for item in value)
