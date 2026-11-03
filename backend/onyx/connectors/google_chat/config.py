from typing import Annotated, Any

from pydantic import field_validator

from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import FieldClass, FieldPolicy, ScopeInclude


def normalize_space_entry(entry: str) -> str:
    """A Spaces entry as it is stored and matched. A space name or id matches
    case-insensitively, with or without the spaces/ prefix."""
    return entry.strip().casefold().removeprefix("spaces/")


class GoogleChatConnectorConfig(ConnectorConfig):
    # Space display names or ids (spaces/AAAA or AAAA). Empty indexes every
    # named space in the organization.
    spaces: Annotated[
        list[str] | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True)),
    ] = None

    # The scope planner diffs this list, so entries are stored in the form
    # they match in, deduped and sorted, and blank entries are dropped. Then
    # "Engineering" and "engineering" never read as a change of scope.
    @field_validator("spaces", mode="before")
    @classmethod
    def _normalize_spaces(cls, value: Any) -> Any:
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            return value
        return sorted(
            {normalize_space_entry(entry) for entry in value if entry.strip()}
        )
