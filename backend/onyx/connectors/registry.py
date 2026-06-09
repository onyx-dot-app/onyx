"""Registry mapping for connector classes."""

from pydantic import BaseModel

from onyx.configs.constants import DocumentSource


class ConnectorMapping(BaseModel):
    module_path: str
    class_name: str


# Mapping of DocumentSource to connector details for lazy loading
CONNECTOR_CLASS_MAP = {
    DocumentSource.JIRA_SERVICE_MANAGEMENT: ConnectorMapping(
        module_path="onyx.connectors.jira_service_management.connector",
        class_name="JiraServiceManagementConnector",
    ),
    DocumentSource.WEB: ConnectorMapping(
        module_path="onyx.connectors.web.connector",
        class_name="WebConnector",
    ),
    DocumentSource.FILE: ConnectorMapping(
        module_path="onyx.connectors.file.connector",
        class_name="LocalFileConnector",
    ),
}