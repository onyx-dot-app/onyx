from collections.abc import Generator

from ee.onyx.external_permissions.egnyte.connector import egnyte_connector
from ee.onyx.external_permissions.perm_sync_types import (
    FetchAllDocumentsFunction,
    FetchAllDocumentsIdsFunction,
)
from ee.onyx.external_permissions.utils import generic_doc_sync
from onyx.access.models import ElementExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.db.models import ConnectorCredentialPair
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface

EGNYTE_DOC_SYNC_LABEL = "egnyte_doc_sync"


def egnyte_doc_sync(
    cc_pair: ConnectorCredentialPair,
    fetch_all_existing_docs_fn: FetchAllDocumentsFunction,  # noqa: ARG001
    fetch_all_existing_docs_ids_fn: FetchAllDocumentsIdsFunction,
    callback: IndexingHeartbeatInterface | None,
) -> Generator[ElementExternalAccess, None, None]:
    yield from generic_doc_sync(
        cc_pair=cc_pair,
        fetch_all_existing_docs_ids_fn=fetch_all_existing_docs_ids_fn,
        callback=callback,
        doc_source=DocumentSource.EGNYTE,
        slim_connector=egnyte_connector(cc_pair),
        label=EGNYTE_DOC_SYNC_LABEL,
    )
