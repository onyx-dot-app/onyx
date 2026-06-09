from collections.abc import Generator
from typing_extensions import override

from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.jira.connector import JiraConnector
from onyx.utils.logger import setup_logger

logger = setup_logger()

class JiraServiceManagementConnector(JiraConnector):
    @property
    def source(self) -> DocumentSource:
        return DocumentSource.JIRA_SERVICE_MANAGEMENT

    def _get_service_desk_project_keys(self) -> list[str]:
        """
        Fetches all project keys explicitly categorized as Service Desks
        using proper Atlassian API pagination cursor mechanics.
        """
        project_keys: list[str] = []
        start_at = 0
        limit = 50
        is_last_page = False

        # Accessing the correct base class Jira client session properties
        session = self.jira_client._session
        
        while not is_last_page:
            url = f"{self.jira_base}/rest/servicedeskapi/servicedesk?start={start_at}&limit={limit}"
            try:
                response = session.get(url)
                response.raise_for_status()
                data = response.json()
                
                values = data.get("values", [])
                for project in values:
                    if "projectKey" in project:
                        project_keys.append(project["projectKey"])
                
                # Check pagination status securely
                is_last_page = data.get("isLastPage", True)
                if not is_last_page:
                    start_at += len(values)
                    if len(values) == 0:  # Safety check to prevent infinite loops
                        break
            except Exception as e:
                logger.error("Failed to fetch Jira Service Management projects: %s", e)
                break

        return project_keys

    @override
    def retrieve_all_slim_docs(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> Generator[GenerateSlimDocumentOutput, None, None]:
        """
        Dynamically filters project indexing targets to clean JSM scopes.
        """
        try:
            jsm_projects = self._get_service_desk_project_keys()
            
            # If the user specified a project in their connector configs, check it safely
            if self.jira_project:
                if self.jira_project in jsm_projects:
                    logger.info("Scoping JSM indexer execution to project: %s", self.jira_project)
                else:
                    logger.warning("Configured project %s is not a designated JSM Service Desk.", self.jira_project)
                    return
            else:
                logger.info("Discovered active JSM Service Desk project scopes: %s", jsm_projects)
                # Future expansion: Inject dynamic broad scopes if required by framework
                
        except Exception as e:
            logger.error("Error setting up JSM integration scopes: %s", e)

        yield from super().retrieve_all_slim_docs(start, end)