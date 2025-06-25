from collections.abc import Generator

from ee.onyx.external_permissions.perm_sync_types import FetchAllDocumentsFunction
from onyx.access.models import DocExternalAccess
from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.models import SlimDocument
from onyx.db.models import ConnectorCredentialPair
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _make_missing_docs_inaccessible(
    fetched_slim_docs: list[SlimDocument],
    existing_doc_ids: list[str],
) -> Generator[DocExternalAccess]:
    """
    Given the fetched `SlimDocument`s and the existing doc-ids, the existing doc-ids whose ids were *not* fetched will be marked
    inaccessible.

    Each one of the fetched `SlimDocument`'s `DocExternalAccess` will be yielded.
    """
    fetched_ids = {doc.id for doc in fetched_slim_docs}
    existing_ids = set(existing_doc_ids)

    missing_ids = existing_ids - fetched_ids
    if missing_ids:
        logger.warning(
            f"Found {len(missing_ids)=} documents that are in the DB but not present in fetch. Making them inaccessible."
        )

        for missing_id in missing_ids:
            logger.warning(f"Removing access for {missing_id=}")
            yield DocExternalAccess(
                doc_id=missing_id,
                external_access=ExternalAccess.empty(),
            )


def generic_doc_sync(
    cc_pair: ConnectorCredentialPair,
    fetch_all_existing_docs_fn: FetchAllDocumentsFunction,
    callback: IndexingHeartbeatInterface | None,
    doc_source: DocumentSource,
    slim_connector: SlimConnector,
    label: str,
) -> Generator[DocExternalAccess, None, None]:
    """
    TODO
    """
    logger.info(f"Starting {doc_source} doc sync for CC Pair ID: {cc_pair.id}")

    logger.info(f"Querying existing document IDs for CC Pair ID: {cc_pair.id}")
    existing_doc_ids = fetch_all_existing_docs_fn()

    logger.info(f"Fetching all slim documents from {doc_source}")
    for doc_batch in slim_connector.retrieve_all_slim_documents(callback=callback):
        logger.info(f"Got {len(doc_batch)} slim documents from {doc_source}")

        # `existing_doc_ids` and `doc_batch` may be non-subsets of one another (i.e., `existing_doc_ids` is not a subset of
        # `doc_batch`, and `doc_batch` is not a subset of `existing_doc_ids`).
        #
        # In that case, we want to:
        # 1. Make private all the ids which are in `existing_doc_ids` and are *not* in `doc_batch`.
        # 2. Yield the rest of the `ExternalAccess`s.

        yield from _make_missing_docs_inaccessible(
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
                raise RuntimeError(f"{label}: Stop signal detected")
            callback.progress(label, 1)

    logger.info(f"Finished {doc_source} doc sync")
