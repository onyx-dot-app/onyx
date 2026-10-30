"""Pydantic config for the Jira Service Management connector."""
from typing import Any

from pydantic import BaseModel
from pydantic import model_validator

from onyx.connectors.jira_service_management.jira_service_management_connector import (
    _validate_project_key,
)


class JiraServiceManagementConnectorConfig(BaseModel):
    """Configuration for :class:`JiraServiceManagementConnector`.

    ``base_url`` is the Atlassian site root (e.g. ``https://acme.atlassian.net``).
    ``project_key`` scopes indexing to a single JSM project.
    """

    base_url: str
    project_key: str

    @model_validator(mode="after")
    def _validate_fields(self) -> "JiraServiceManagementConnectorConfig":
        _validate_project_key(self.project_key)
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("base_url must be an http(s) URL")
        return self
