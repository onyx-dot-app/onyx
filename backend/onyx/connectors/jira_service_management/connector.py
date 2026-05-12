from datetime import datetime
from datetime import timezone

from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.jira.connector import INDEX_BATCH_SIZE
from onyx.connectors.jira.connector import JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.connector import JiraConnectorCheckpoint
from onyx.connectors.models import Document


class JiraServiceManagementConnector(JiraConnector):
    """Connector for pulling Jira Service Management issues from one service project.

    Jira Service Management requests are backed by Jira issues and are available
    through Jira search APIs. Reuse the Jira connector implementation while
    exposing a distinct document source and requiring a single service project.
    """

    def __init__(
        self,
        jira_base_url: str,
        project_key: str,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
        jql_query: str | None = None,
        scoped_token: bool = False,
    ) -> None:
        if not project_key:
            raise ValueError(
                "Jira Service Management connector requires a project_key."
            )

        super().__init__(
            jira_base_url=jira_base_url,
            project_key=project_key,
            comment_email_blacklist=comment_email_blacklist,
            batch_size=batch_size,
            labels_to_skip=labels_to_skip,
            jql_query=jql_query,
            scoped_token=scoped_token,
        )

    def _get_jql_query(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> str:
        start_date_str = datetime.fromtimestamp(start, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M"
        )
        end_date_str = datetime.fromtimestamp(end, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M"
        )

        project_clause = f"project = '{self.jira_project}'"
        if self.jql_query:
            base_jql = f"({self.jql_query}) AND {project_clause}"
        else:
            base_jql = project_clause

        return (
            f"{base_jql} AND updated >= '{start_date_str}' "
            f"AND updated <= '{end_date_str}'"
        )

    def _load_from_checkpoint(
        self, jql: str, checkpoint: JiraConnectorCheckpoint, include_permissions: bool
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        new_checkpoint = yield from self._load_from_jira_checkpoint(
            jql, checkpoint, include_permissions
        )
        return new_checkpoint

    def _load_from_jira_checkpoint(
        self, jql: str, checkpoint: JiraConnectorCheckpoint, include_permissions: bool
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        parent_output = super()._load_from_checkpoint(jql, checkpoint, include_permissions)
        while True:
            try:
                item = next(parent_output)
            except StopIteration as e:
                return e.value

            if isinstance(item, Document):
                item.source = DocumentSource.JIRA_SERVICE_MANAGEMENT
            yield item
