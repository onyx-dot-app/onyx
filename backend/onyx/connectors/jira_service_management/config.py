from typing import Annotated, Any

from pydantic import field_validator

from onyx.connectors.connector_config import BaseUrlCredentialBinding, ConnectorConfig
from onyx.connectors.field_policy import FieldClass, FieldPolicy, ScopeInclude


class JiraServiceManagementConnectorConfig(
    BaseUrlCredentialBinding, ConnectorConfig
):
    # Optional Jira Service Management project key (e.g. "ITSM" or "SUP").
    # Leaving it empty indexes requests across all readable service desks.
    project_key: Annotated[
        str | None,
        FieldPolicy(
            FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True)
        ),
    ] = None

    @field_validator("project_key", mode="before")
    @classmethod
    def _normalize_project_key(cls, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped.upper() if stripped else None
        return value
