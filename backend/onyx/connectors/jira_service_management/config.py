"""Pydantic config for the Jira Service Management connector."""
from pydantic import BaseModel


class JiraServiceManagementConnectorConfig(BaseModel):
    """Configuration for :class:`JiraServiceManagementConnector`.

    The JSM project key to index. ``base_url`` is supplied via credentials/config
    at instantiation time; ``project_key`` is the scoping identifier.
    """

    project_key: str
