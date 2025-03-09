import datetime
from typing import Any

from onyx.configs.app_configs import CONTINUE_ON_CONNECTOR_FAILURE
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.asana import asana_api
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()


class AsanaConnector(LoadConnector, PollConnector):
    def __init__(
        self,
        asana_workspace_id: str,
        asana_project_ids: str | None = None,
        asana_team_id: str | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        continue_on_failure: bool = CONTINUE_ON_CONNECTOR_FAILURE,
    ) -> None:
        self.workspace_id = asana_workspace_id
        self.project_ids_to_index: list[str] | None = (
            asana_project_ids.split(",") if asana_project_ids is not None else None
        )
        self.asana_team_id = asana_team_id
        self.batch_size = batch_size
        self.continue_on_failure = continue_on_failure
        logger.info(
            f"AsanaConnector initialized with workspace_id: {asana_workspace_id}"
        )

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.api_token = credentials["asana_api_token_secret"]
        self.asana_client = asana_api.AsanaAPI(
            api_token=self.api_token,
            workspace_gid=self.workspace_id,
            team_gid=self.asana_team_id,
        )
        logger.info("Asana credentials loaded and API client initialized")
        return None

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch | None
    ) -> GenerateDocumentsOutput:
        start_time = datetime.datetime.fromtimestamp(start).isoformat()
        logger.info(f"Starting Asana poll from {start_time}")
        asana = asana_api.AsanaAPI(
            api_token=self.api_token,
            workspace_gid=self.workspace_id,
            team_gid=self.asana_team_id,
        )
        docs_batch: list[Document] = []
        tasks = asana.get_tasks(self.project_ids_to_index, start_time)

        for task in tasks:
            doc = self._message_to_doc(task)
            docs_batch.append(doc)

            if len(docs_batch) >= self.batch_size:
                logger.info(f"Yielding batch of {len(docs_batch)} documents")
                yield docs_batch
                docs_batch = []

        if docs_batch:
            logger.info(f"Yielding final batch of {len(docs_batch)} documents")
            yield docs_batch

        logger.info("Asana poll completed")

    def load_from_state(self) -> GenerateDocumentsOutput:
        logger.notice("Starting full index of all Asana tasks")
        return self.poll_source(start=0, end=None)

    def _message_to_doc(self, task: asana_api.AsanaTask) -> Document:
        logger.debug(f"Converting Asana task {task.id} to Document")
        return Document(
            id=task.id,
            sections=[TextSection(link=task.link, text=task.text)],
            doc_updated_at=task.last_modified,
            source=DocumentSource.ASANA,
            semantic_identifier=task.title,
            metadata={
                "group": task.project_gid,
                "project": task.project_name,
            },
        )


if __name__ == "__main__":
    import time
    import os

    logger.notice("Starting Asana connector test")
    connector = AsanaConnector(
        os.environ["WORKSPACE_ID"],
        os.environ["PROJECT_IDS"],
        os.environ["TEAM_ID"],
    )
    connector.load_credentials(
        {
            "asana_api_token_secret": os.environ["API_TOKEN"],
        }
    )
    logger.info("Loading all documents from Asana")
    all_docs = connector.load_from_state()
    current = time.time()
    one_day_ago = current - 24 * 60 * 60  # 1 day
    logger.info("Polling for documents updated in the last 24 hours")
    latest_docs = connector.poll_source(one_day_ago, current)
    for docs in latest_docs:
        for doc in docs:
            print(doc.id)
    logger.notice("Asana connector test completed")
