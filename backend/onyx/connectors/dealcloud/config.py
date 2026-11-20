from typing import Annotated, Any

from pydantic import field_validator

from onyx.connectors.connector_config import BaseUrlCredentialBinding, ConnectorConfig
from onyx.connectors.field_policy import FieldClass, FieldPolicy, ScopeInclude


class DealCloudConnectorConfig(BaseUrlCredentialBinding, ConnectorConfig):
    # Object api names such as Company or Deal. Empty indexes every object the
    # API user can read, except Attachment.
    entry_types: Annotated[
        list[str] | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True)),
    ] = None

    # The scope planner diffs this list, so it is trimmed, deduped and sorted.
    # It is also lowercased: the connector matches API names without regard to
    # case, and a change of case alone must not read as a change of scope.
    @field_validator("entry_types", mode="before")
    @classmethod
    def _normalize_entry_types(cls, value: Any) -> Any:
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            return value
        return sorted({entry.strip().lower() for entry in value if entry.strip()})
