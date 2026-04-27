from typing import Any

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.connector import JiraConnectorCheckpoint
from onyx.connectors.jira_service_management.utils import _JSM_API_BASE
from onyx.connectors.jira_service_management.utils import _JSM_SERVICEDESK_PATH
from onyx.connectors.models import Document
from onyx.utils.logger import setup_logger

logger = setup_logger()


class JiraServiceManagementConnector(JiraConnector):
    def __init__(
        self,
        jira_base_url: str,
        jsm_project_key: str,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
        scoped_token: bool = False,
    ) -> None:
        super().__init__(
            jira_base_url=jira_base_url,
            project_key=jsm_project_key,
            comment_email_blacklist=comment_email_blacklist,
            batch_size=batch_size,
            labels_to_skip=labels_to_skip,
            scoped_token=scoped_token,
        )
        self._service_desk_id: int | None = None

    @property
    def _document_source(self) -> DocumentSource:
        return DocumentSource.JIRA_SERVICE_MANAGEMENT

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        result = super().load_credentials(credentials)
        self._service_desk_id = self._fetch_service_desk_id()
        return result

    def _fetch_service_desk_id(self) -> int | None:
        if not self.jira_project:
            return None
        try:
            server = self.jira_client._options["server"].rstrip("/")
            url = f"{server}/{_JSM_API_BASE}/{_JSM_SERVICEDESK_PATH}"
            response = self.jira_client._session.get(
                url, params={"projectKey": self.jira_project}
            )
            response.raise_for_status()
            values = response.json().get("values", [])
            if values:
                return int(values[0]["id"])
        except Exception as e:
            logger.warning(
                f"Could not fetch service desk ID for project '{self.jira_project}': {e}"
            )
        return None

    def validate_connector_settings(self) -> None:
        super().validate_connector_settings()
        if not self.jira_project:
            return
        # The parent already validated credentials and project existence.
        # One additional round-trip here is acceptable to inspect projectTypeKey,
        # which the parent does not expose.
        try:
            project = self.jira_client.project(self.jira_project)
            project_type = project.raw.get("projectTypeKey")
            if project_type != "service_desk":
                raise ConnectorValidationError(
                    f"Project '{self.jira_project}' is not a Jira Service Management project "
                    f"(projectTypeKey={project_type!r}). "
                    f"Please provide the key of a Service Desk project."
                )
        except ConnectorValidationError:
            raise
        except Exception as e:
            raise ConnectorValidationError(
                f"Could not verify project type for '{self.jira_project}': {e}"
            ) from e

    def _load_from_checkpoint(
        self,
        jql: str,
        checkpoint: JiraConnectorCheckpoint,
        include_permissions: bool,
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        gen = super()._load_from_checkpoint(jql, checkpoint, include_permissions)
        try:
            while True:
                item = next(gen)
                if isinstance(item, Document) and self._service_desk_id is not None:
                    issue_key = item.metadata.get("key")
                    if issue_key:
                        # jira_base is already rstrip("/") from JiraConnector.__init__
                        item.metadata["customer_portal_url"] = (
                            f"{self.jira_base}/servicedesk/customer/portal"
                            f"/{self._service_desk_id}/{issue_key}"
                        )
                yield item
        except StopIteration as e:
            return e.value  # the updated JiraConnectorCheckpoint
