"""
Rules defined here:
https://confluence.atlassian.com/conf85/check-who-can-view-a-page-1283360557.html
"""

from collections.abc import Generator

from ee.onyx.external_permissions.perm_sync_types import FetchAllDocumentsFunction
from onyx.access.models import DocExternalAccess
from onyx.access.models import ExternalAccess
from onyx.connectors.confluence.connector import ConfluenceConnector
from onyx.connectors.credentials_provider import OnyxDBCredentialsProvider
from onyx.connectors.models import SlimDocument
from onyx.db.models import ConnectorCredentialPair
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


def confluence_doc_sync(
    cc_pair: ConnectorCredentialPair,
    fetch_all_existing_docs_fn: FetchAllDocumentsFunction,
    callback: IndexingHeartbeatInterface | None,
) -> Generator[DocExternalAccess, None, None]:
    """
    Fetches document permissions from Confluence and yields DocExternalAccess objects.
    Compares fetched documents against existing documents in the DB for the connector.
    If a document exists in the DB but not in the Confluence fetch, it's marked as restricted.
    """
    logger.info(f"Starting confluence doc sync for CC Pair ID: {cc_pair.id}")
    confluence_connector = ConfluenceConnector(
        **cc_pair.connector.connector_specific_config
    )

    provider = OnyxDBCredentialsProvider(
        get_current_tenant_id(), "confluence", cc_pair.credential_id
    )
    confluence_connector.set_credentials_provider(provider)

    slim_docs: list[SlimDocument] = []
    logger.info("Fetching all slim documents from confluence")
    for doc_batch in confluence_connector.retrieve_all_slim_documents(
        callback=callback
    ):
        logger.info(f"Got {len(doc_batch)} slim documents from confluence")
        if callback:
            if callback.should_stop():
                raise RuntimeError("confluence_doc_sync: Stop signal detected")

            callback.progress("confluence_doc_sync", 1)

        slim_docs.extend(doc_batch)

    # Find documents that are no longer accessible in Confluence
    logger.info(f"Querying existing document IDs for CC Pair ID: {cc_pair.id}")
    existing_doc_ids = fetch_all_existing_docs_fn()

    # Find missing doc IDs
    fetched_doc_ids = {doc.id for doc in slim_docs}
    missing_doc_ids = set(existing_doc_ids) - fetched_doc_ids

    # Yield access removal for missing docs. Better to be safe.
    if missing_doc_ids:
        logger.warning(
            f"Found {len(missing_doc_ids)} documents that are in the DB but "
            "not present in Confluence fetch. Making them inaccessible."
        )
        for missing_id in missing_doc_ids:
            logger.warning(f"Removing access for document ID: {missing_id}")
            yield DocExternalAccess(
                doc_id=missing_id,
                external_access=ExternalAccess(
                    external_user_emails=set(),
                    external_user_group_ids=set(),
                    is_public=False,
                ),
            )

    for doc in slim_docs:
        if not doc.external_access:
            raise RuntimeError(f"No external access found for document ID: {doc.id}")

        yield DocExternalAccess(
            doc_id=doc.id,
            external_access=doc.external_access,
        )

    logger.info("Finished confluence doc sync")
