import os
from collections.abc import Generator
from datetime import datetime
from datetime import timezone

from github import Github

from ee.onyx.external_permissions.perm_sync_types import FetchAllDocumentsFunction
from onyx.access.models import DocExternalAccess
from onyx.connectors.connector_runner import CheckpointOutputWrapper
from onyx.connectors.github.connector import GithubConnector
from onyx.connectors.github.connector import GithubConnectorCheckpoint
from onyx.connectors.github.connector import SerializedRepository
from onyx.connectors.interfaces import CheckpointedSlimConnector
from onyx.connectors.models import SlimDocument
from onyx.db.models import ConnectorCredentialPair
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()


def github_doc_sync(
    cc_pair: ConnectorCredentialPair | None = None,
    fetch_all_existing_docs_fn: FetchAllDocumentsFunction | None = None,
    callback: IndexingHeartbeatInterface | None = None,
) -> Generator[DocExternalAccess, None, None]:
    # github_connector = GithubConnector(
    #     **cc_pair.connector.connector_specific_config
    # )
    # github_connector.load_credentials(cc_pair.credential.credential_json)
    logger.info("Starting GitHub document sync...")
    github_connector = GithubConnector(
        repo_owner=os.environ["REPO_OWNER"],
        repositories=os.environ.get("REPOSITORIES"),
        include_issues=True,  # Enable issues processing
    )
    github_connector.load_credentials(
        {"github_access_token": os.environ["ACCESS_TOKEN_GITHUB"]}
    )

    if not isinstance(github_connector, CheckpointedSlimConnector):
        raise TypeError(
            f"Expected CheckpointedSlimConnector, got {type(github_connector)}"
        )
    logger.info("GitHub connector initialized successfully.")
    checkpoint = github_connector.build_dummy_checkpoint()
    current_time = datetime.now(timezone.utc)
    start_time = 0.0
    logger.info(f"Checkpoint initialized: {checkpoint}")

    while checkpoint.has_more:
        slim_doc_generator = github_connector.checkpointed_retrieve_all_slim_documents(
            start=start_time,
            end=current_time.timestamp(),
            checkpoint=checkpoint,
        )

        for slim_doc, failure, new_checkpoint in CheckpointOutputWrapper[
            GithubConnectorCheckpoint
        ]()(slim_doc_generator):
            if new_checkpoint:
                logger.info(f"New checkpoint received: {new_checkpoint}")
                checkpoint = new_checkpoint
                continue

            if slim_doc:
                if isinstance(slim_doc, SlimDocument):
                    yield DocExternalAccess(
                        doc_id=slim_doc.id,
                        external_access=slim_doc.external_access,
                    )


def _get_repo_with_updated_teams(
    github_client: Github, checkpoint: GithubConnectorCheckpoint
) -> GithubConnectorCheckpoint:

    if not _teams_updated(checkpoint.cached_repo, github_client):
        return checkpoint

    if checkpoint.cached_repo_ids:
        next_id = checkpoint.cached_repo_ids.pop()
        next_repo = github_client.get_repo(next_id)
        checkpoint.cached_repo = SerializedRepository(
            id=next_id,
            headers=next_repo.raw_headers,
            raw_data=next_repo.raw_data,
        )

    return _get_repo_with_updated_teams(
        github_client=github_client, checkpoint=checkpoint
    )


def _teams_updated(repo: SerializedRepository, github_client: Github) -> bool:
    return False


if __name__ == "__main__":
    # Consume the generator to actually execute the sync
    for doc_access in github_doc_sync():
        logger.info(f"Processed document: {doc_access.doc_id}")
    logger.info("GitHub document sync completed.")
