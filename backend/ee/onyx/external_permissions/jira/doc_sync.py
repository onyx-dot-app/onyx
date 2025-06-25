from collections.abc import Generator

from ee.onyx.external_permissions.perm_sync_types import FetchAllDocumentsFunction
from ee.onyx.external_permissions.utils import make_missing_docs_inaccessible
from onyx.access.models import DocExternalAccess
from onyx.connectors.jira.connector import JiraConnector
from onyx.db.models import ConnectorCredentialPair
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

JIRA_DOC_SYNC_TAG = "jira_doc_sync"


def jira_doc_sync(
    cc_pair: ConnectorCredentialPair,
    fetch_all_existing_docs_fn: FetchAllDocumentsFunction,
    callback: IndexingHeartbeatInterface | None = None,
) -> Generator[DocExternalAccess, None, None]:
    logger.info(f"{JIRA_DOC_SYNC_TAG}: Starting jira doc sync for {cc_pair.id=}")

    jira_connector = JiraConnector(
        **cc_pair.connector.connector_specific_config,
    )
    jira_connector.load_credentials(cc_pair.credential.credential_json)

    existing_doc_ids = fetch_all_existing_docs_fn()

    for doc_batch in jira_connector.retrieve_all_slim_documents(callback=callback):
        logger.info(
            f"{JIRA_DOC_SYNC_TAG}: Got {len(doc_batch)} slim documents from jira"
        )

        # `existing_doc_ids` and `doc_batch` may be non-subsets of one another (i.e., `existing_doc_ids` is not a subset of
        # `doc_batch`, and `doc_batch` is not a subset of `existing_doc_ids`).
        #
        # In that case, we want to:
        # 1. Make private all the ids which are in `existing_doc_ids` and are *not* in `doc_batch`.
        # 2. Yield the rest of the `ExternalAccess`s.

        yield from make_missing_docs_inaccessible(
            fetched_slim_docs=doc_batch,
            existing_doc_ids=existing_doc_ids,
        )

        for doc in doc_batch:
            if not doc.external_access:
                raise RuntimeError(
                    f"{JIRA_DOC_SYNC_TAG}: No external access found for {doc.id=}"
                )

            yield DocExternalAccess(
                doc_id=doc.id,
                external_access=doc.external_access,
            )

        if callback:
            if callback.should_stop():
                raise RuntimeError(f"{JIRA_DOC_SYNC_TAG}: Stop signal detected")

            callback.progress(JIRA_DOC_SYNC_TAG, 1)

    logger.info(f"{JIRA_DOC_SYNC_TAG} Finished jira doc sync")
