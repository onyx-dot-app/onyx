from typing import Annotated, Any

from pydantic import field_validator

from onyx.connectors.connector_config import BaseUrlCredentialBinding, ConnectorConfig
from onyx.connectors.field_policy import FieldClass, FieldPolicy, ScopeInclude


class YouTrackConnectorConfig(BaseUrlCredentialBinding, ConnectorConfig):
    # Project short names such as ABC. Empty indexes every project the token
    # can read.
    projects: Annotated[
        list[str] | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True)),
    ] = None

    # The scope planner diffs this list, so it is trimmed, deduped and sorted,
    # and blank entries are dropped.
    @field_validator("projects", mode="before")
    @classmethod
    def _normalize_projects(cls, value: Any) -> Any:
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            return value
        return sorted({entry.strip() for entry in value if entry.strip()})
