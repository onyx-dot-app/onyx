from collections.abc import Generator
from collections.abc import Generator
from typing import Any

from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.connector import JiraConnectorCheckpoint
from onyx.connectors.models import Document
from onyx.utils.logger import setup_logger

logger = setup_logger()

class JsmConnector(JiraConnector):
    """
    Jira Service Management (JSM) Connector.
    Heavily reuses JiraConnector logic but ensures DocumentSource is JIRA_SERVICE_MANAGEMENT.
    """

    def __init__(
        self,
        jira_base_url: str,
        project_key: str | None = None,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
        jql_query: str | None = None,
        scoped_token: bool = False,
    ) -> None:
        super().__init__(
            jira_base_url=jira_base_url,
            project_key=project_key,
            comment_email_blacklist=comment_email_blacklist,
            batch_size=batch_size,
            labels_to_skip=labels_to_skip,
            jql_query=jql_query,
            scoped_token=scoped_token,
        )

    def _wrap_yield_with_jsm_source(
        self, generator: Generator[Any, None, JiraConnectorCheckpoint]
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        """
        Wraps the standard Jira generator to ensure all yielding Documents 
        have the JIRA_SERVICE_MANAGEMENT source and enriched JSM metadata.
        """
        try:
            while True:
                item = next(generator)
                if isinstance(item, Document):
                    item.source = DocumentSource.JIRA_SERVICE_MANAGEMENT
                    
                    # Refine metadata for JSM specific context if available
                    # Note: These fields are common in JSM environments
                    if "request-type" in item.metadata:
                        item.metadata["jsm_request_type"] = item.metadata.pop("request-type")
                    
                    if "customer-satisfaction" in item.metadata:
                        item.metadata["jsm_satisfaction_score"] = item.metadata.pop("customer-satisfaction")

                yield item
        except StopIteration as e:
            return e.value

    @override
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraConnectorCheckpoint,
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        # JiraConnector.load_from_checkpoint already uses _get_jql_query(start, end)
        # which correctly includes the end bound.
        gen = super().load_from_checkpoint(start, end, checkpoint)
        return self._wrap_yield_with_jsm_source(gen)

    @override
    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraConnectorCheckpoint,
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        gen = super().load_from_checkpoint_with_perm_sync(start, end, checkpoint)
        return self._wrap_yield_with_jsm_source(gen)
