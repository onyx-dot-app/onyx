from typing import Any

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import JiraConnector


class JiraServiceManagementConnector(JiraConnector):
    def __init__(
        self,
        jira_service_management_base_url: str | None = None,
        jira_base_url: str | None = None,
        **kwargs: Any,
    ):
        # The frontend sends 'jira_service_management_base_url', but the 
        # parent JiraConnector expects 'jira_base_url'. We map it here.
        actual_url = jira_service_management_base_url or jira_base_url
        
        if not actual_url:
            raise ValueError("Jira Service Management Base URL is required")

        super().__init__(jira_base_url=actual_url, **kwargs)

    @property
    def source(self) -> DocumentSource:
        return DocumentSource.JIRA_SERVICE_MANAGEMENT