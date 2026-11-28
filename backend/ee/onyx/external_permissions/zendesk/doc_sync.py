from collections.abc import Generator

from ee.onyx.external_permissions.perm_sync_types import (
    FetchAllDocumentsFunction,
    FetchAllDocumentsIdsFunction,
)
from ee.onyx.external_permissions.utils import generic_doc_sync
from ee.onyx.external_permissions.zendesk.connector import zendesk_connector
from onyx.access.models import ElementExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.db.models import ConnectorCredentialPair
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface

ZENDESK_DOC_SYNC_LABEL = "zendesk_doc_sync"


def zendesk_doc_sync(
    cc_pair: ConnectorCredentialPair,
    fetch_all_existing_docs_fn: FetchAllDocumentsFunction,  # noqa: ARG001
    fetch_all_existing_docs_ids_fn: FetchAllDocumentsIdsFunction,
    callback: IndexingHeartbeatInterface | None,
) -> Generator[ElementExternalAccess, None, None]:
    connector = zendesk_connector(cc_pair)
    # The scheduled doc sync is not validated for it, and a token that lost
    # admin access lists fewer articles and tickets: the rest would go private.
    connector.validate_perm_sync()
    yield from generic_doc_sync(
        cc_pair=cc_pair,
        fetch_all_existing_docs_ids_fn=fetch_all_existing_docs_ids_fn,
        callback=callback,
        doc_source=DocumentSource.ZENDESK,
        slim_connector=connector,
        label=ZENDESK_DOC_SYNC_LABEL,
    )
