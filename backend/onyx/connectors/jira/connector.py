import requests
from typing_extensions import override
from collections.abc import Generator

from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.jira.connector import JiraConnector
from onyx.configs.constants import DocumentSource
from onyx.utils.logger import setup_logger

logger = setup_logger()

class JiraServiceManagementConnector(JiraConnector):
    """
    Connector for Jira Service Management (JSM). 
    Inherits auth, checkpointing, and pagination from the standard JiraConnector,
    but enforces JSM scoping and applies the correct DocumentSource metadata.
    """

    @property
    def source(self) -> DocumentSource:
        return DocumentSource.JIRA_SERVICE_MANAGEMENT

    @override
    def _get_projects(self) -> list[str]:
        """
        Fetches only service desk (JSM) projects to prevent mixing 
        traditional software projects into this connector.
        """
        if self.project_keys:
            return self.project_keys

        # Target Atlassian's Service Desk API endpoint to find active service desks
        url = f"{self.base_url}/rest/servicedeskapi/servicedesk"
        try:
            response = self.client._session.get(url)
            response.raise_for_status()
            data = response.json()
            
            # Extract project keys specifically tagged as service desks
            jsm_projects = [
                project["projectKey"] 
                for project in data.get("values", []) 
                if "projectKey" in project
            ]
            return jsm_projects
            
        except Exception as e:
            logger.error(f"Failed to fetch Jira Service Management projects: {e}")
            # Fallback to base class logic if the service desk discovery endpoint fails
            return super()._get_projects()