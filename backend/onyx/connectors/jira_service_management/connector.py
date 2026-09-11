from http import HTTPStatus
from typing import Any

from jira import JIRAError
from requests import RequestException
from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE, JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.constants import DocumentSource
from onyx.connectors.connector_runner import CheckpointOutputWrapper
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.interfaces import (
    CheckpointedConnector,
    CheckpointOutput,
    GenerateSlimDocumentOutput,
    SecondsSinceUnixEpoch,
    SlimConnector,
)
from onyx.connectors.jira.connector import JiraConnector, JiraConnectorCheckpoint
from onyx.connectors.models import TextSection
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface

_SERVICE_DESK_PROJECT_TYPE = "service_desk"


class JiraServiceManagementConnector(
    CheckpointedConnector[JiraConnectorCheckpoint], SlimConnector
):
    """Index one service project through the Jira API using an agent account.

    Access is set in Onyx. Jira project roles do not represent JSM customer access,
    so this connector does not advertise automatic permission sync.
    """

    def __init__(
        self,
        jira_base_url: str,
        project_key: str,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
        scoped_token: bool = False,
    ) -> None:
        project_key = project_key.strip()
        if not project_key:
            raise ConnectorValidationError(
                "Enter a Jira Service Management project key."
            )
        self.project_key = project_key
        self.jira = JiraConnector(
            jira_base_url=jira_base_url,
            project_key=project_key,
            comment_email_blacklist=comment_email_blacklist,
            batch_size=batch_size,
            labels_to_skip=labels_to_skip,
            scoped_token=scoped_token,
        )
        self._validated = False

    @override
    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self._validated = False
        return self.jira.load_credentials(credentials)

    @override
    def validate_connector_settings(self) -> None:
        self._validated = False
        try:
            project = self.jira.jira_client.project(self.project_key)
        except JIRAError as exc:
            if exc.status_code == HTTPStatus.UNAUTHORIZED:
                raise CredentialExpiredError(
                    "Jira credentials are invalid or expired."
                ) from exc
            if exc.status_code == HTTPStatus.FORBIDDEN:
                raise InsufficientPermissionsError(
                    "The Jira account cannot read the service project."
                ) from exc
            if exc.status_code == HTTPStatus.TOO_MANY_REQUESTS:
                raise ConnectorValidationError(
                    "Jira rate limit reached. Retry validation later."
                ) from exc
            raise ConnectorValidationError(
                f"Cannot read service project {self.project_key} "
                f"(HTTP {exc.status_code}). Check the project key and account access."
            ) from exc
        except RequestException as exc:
            raise UnexpectedValidationError(
                "Cannot connect to Jira. Check the base URL and network connection."
            ) from exc

        if project.raw.get("projectTypeKey") != _SERVICE_DESK_PROJECT_TYPE:
            raise ConnectorValidationError(
                "The selected project is not a Jira Service Management project. "
                "Use the Jira connector for other project types."
            )
        self._validated = True

    @override
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraConnectorCheckpoint,
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        if not self._validated:
            self.validate_connector_settings()
        output = self.jira.load_from_checkpoint(start, end, checkpoint)
        for document, hierarchy, failure, next_checkpoint in CheckpointOutputWrapper[
            JiraConnectorCheckpoint
        ]()(output):
            if document is not None:
                sections = document.sections
                # Empty ticket bodies otherwise lose their links during chunking.
                if not any(
                    section.text and section.text.strip() for section in sections
                ):
                    sections = [
                        TextSection(link=document.id, text=document.semantic_identifier)
                    ]
                yield document.model_copy(
                    update={
                        "source": DocumentSource.JIRA_SERVICE_MANAGEMENT,
                        "sections": sections,
                    }
                )
            if hierarchy is not None:
                yield hierarchy
            if failure is not None:
                yield failure
            if next_checkpoint is not None:
                return next_checkpoint
        raise RuntimeError("Jira indexing ended without a checkpoint.")

    @override
    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        if not self._validated:
            self.validate_connector_settings()
        yield from self.jira.retrieve_all_slim_docs(start, end, callback)

    @override
    def build_dummy_checkpoint(self) -> JiraConnectorCheckpoint:
        return self.jira.build_dummy_checkpoint()

    @override
    def validate_checkpoint_json(self, checkpoint_json: str) -> JiraConnectorCheckpoint:
        return self.jira.validate_checkpoint_json(checkpoint_json)
