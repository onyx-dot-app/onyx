from collections.abc import Generator

from ee.onyx.external_permissions.perm_sync_types import FetchAllDocumentsFunction
from ee.onyx.external_permissions.utils import make_missing_docs_inaccessible
from onyx.access.models import DocExternalAccess
from onyx.connectors.models import SlimDocument
from onyx.connectors.onyx_jira.connector import JiraConnector
from onyx.db.models import ConnectorCredentialPair
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

JIRA_DOC_SYNC_TAG = "jira_doc_sync"


def jira_doc_sync(
    cc_pair: ConnectorCredentialPair,
    fetch_all_existing_docs_fn: FetchAllDocumentsFunction,
    callback: IndexingHeartbeatInterface | None,
) -> Generator[DocExternalAccess, None, None]:
    logger.info(f"{JIRA_DOC_SYNC_TAG}: Starting jira doc sync for {cc_pair.id=}")

    jc = JiraConnector(
        **cc_pair.connector.connector_specific_config,
    )

    docs: list[SlimDocument] = []

    for doc_batch in jc.retrieve_all_slim_documents(callback=callback):
        logger.info(
            f"{JIRA_DOC_SYNC_TAG}: Got {len(doc_batch)} slim documents from jira"
        )

        if callback:
            if callback.should_stop():
                raise RuntimeError(f"{JIRA_DOC_SYNC_TAG}: Stop signal detected")

            callback.progress(JIRA_DOC_SYNC_TAG, 1)

        docs.extend(doc_batch)

    existing_doc_ids = fetch_all_existing_docs_fn()
    yield from make_missing_docs_inaccessible(
        fetched_slim_docs=docs,
        existing_doc_ids=existing_doc_ids,
    )

    for doc in docs:
        if not doc.external_access:
            raise RuntimeError(
                f"{JIRA_DOC_SYNC_TAG}: No external access found for {doc.id=}"
            )

        yield DocExternalAccess(
            doc_id=doc.id,
            external_access=doc.external_access,
        )

    logger.info(f"{JIRA_DOC_SYNC_TAG} Finished jira doc sync")
