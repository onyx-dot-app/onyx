from collections.abc import Generator

from ee.onyx.external_permissions.perm_sync_types import FetchAllDocumentsIdsFunction
from onyx.access.models import DocExternalAccess
from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import SlimConnectorWithPermSync
from onyx.db.models import ConnectorCredentialPair
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()


def generic_doc_sync(
    cc_pair: ConnectorCredentialPair,
    fetch_all_existing_docs_ids_fn: FetchAllDocumentsIdsFunction,
    callback: IndexingHeartbeatInterface | None,
    doc_source: DocumentSource,
    slim_connector: SlimConnectorWithPermSync,
    label: str,
) -> Generator[DocExternalAccess, None, None]:
    """
    A convenience function for performing a generic document synchronization.

    Notes:
    A generic doc sync includes:
        - fetching existing docs
        - fetching *all* new (slim) docs
        - yielding external-access permissions for existing docs which do not exist in the newly fetched slim-docs set (with their
        `external_access` set to "private")
        - yielding external-access permissions for newly fetched docs

    Returns:
        A `Generator` which yields existing and newly fetched external-access permissions.
    """

    logger.info(f"Starting {doc_source} doc sync for CC Pair ID: {cc_pair.id}")

    newly_fetched_doc_ids: set[str] = set()

    logger.info(f"Fetching all slim documents from {doc_source}")
    for doc_batch in slim_connector.retrieve_all_slim_docs_perm_sync(callback=callback):
        logger.info(f"Got {len(doc_batch)} slim documents from {doc_source}")

        if callback:
            if callback.should_stop():
                raise RuntimeError(f"{label}: Stop signal detected")
            callback.progress(label, 1)

        for doc in doc_batch:
            if not doc.external_access:
                raise RuntimeError(
                    f"No external access found for document ID; {cc_pair.id=} {doc_source=} {doc.id=}"
                )

            newly_fetched_doc_ids.add(doc.id)

            yield DocExternalAccess(
                doc_id=doc.id,
                external_access=doc.external_access,
            )

    logger.info(f"Querying existing document IDs for CC Pair ID: {cc_pair.id=}")
    existing_doc_ids: list[str] = fetch_all_existing_docs_ids_fn()

    missing_doc_ids = set(existing_doc_ids) - newly_fetched_doc_ids

    if not missing_doc_ids:
        return

    logger.warning(
        f"Found {len(missing_doc_ids)=} documents that are in the DB but not present in fetch. Making them inaccessible."
    )

    for missing_id in missing_doc_ids:
        logger.warning(f"Removing access for {missing_id=}")
        yield DocExternalAccess(
            doc_id=missing_id,
            external_access=ExternalAccess.empty(),
        )

    logger.info(f"Finished {doc_source} doc sync")
