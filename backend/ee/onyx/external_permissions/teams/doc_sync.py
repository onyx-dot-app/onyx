from collections.abc import Generator

from ee.onyx.external_permissions.perm_sync_types import FetchAllDocumentsFunction
from ee.onyx.external_permissions.utils import make_missing_docs_inaccessible
from onyx.access.models import DocExternalAccess
from onyx.connectors.teams.connector import TeamsConnector
from onyx.db.models import ConnectorCredentialPair
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()


TEAMS_DOC_SYNC_LABEL = "teams_doc_sync"


def teams_doc_sync(
    cc_pair: ConnectorCredentialPair,
    fetch_all_existing_docs_fn: FetchAllDocumentsFunction,
    callback: IndexingHeartbeatInterface | None,
) -> Generator[DocExternalAccess, None, None]:
    logger.info(f"Starting teams doc sync for CC Pair ID: {cc_pair.id}")
    teams_connector = TeamsConnector(
        **cc_pair.connector.connector_specific_config,
    )
    teams_connector.load_credentials(cc_pair.credential.credential_json)

    logger.info(f"Querying existing document IDs for CC Pair ID: {cc_pair.id}")
    existing_doc_ids = fetch_all_existing_docs_fn()

    logger.info("Fetching all slim documents from teams")
    for doc_batch in teams_connector.retrieve_all_slim_documents(callback=callback):
        logger.info(f"Got {len(doc_batch)} slim documents from teams")

        yield from make_missing_docs_inaccessible(
            fetched_slim_docs=doc_batch,
            existing_doc_ids=existing_doc_ids,
        )

        for doc in doc_batch:
            if not doc.external_access:
                raise RuntimeError(
                    f"No external access found for document ID: {doc.id}"
                )

            yield DocExternalAccess(
                doc_id=doc.id,
                external_access=doc.external_access,
            )

        if callback:
            if callback.should_stop():
                raise RuntimeError(f"{TEAMS_DOC_SYNC_LABEL}: Stop signal detected")
            callback.progress(TEAMS_DOC_SYNC_LABEL, 1)

    logger.info("Finished teams doc sync")
