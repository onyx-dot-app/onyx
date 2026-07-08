from collections.abc import Generator
from typing import Any

from ee.onyx.external_permissions.perm_sync_types import FetchAllDocumentsFunction
from ee.onyx.external_permissions.perm_sync_types import FetchAllDocumentsIdsFunction
from ee.onyx.external_permissions.utils import generic_doc_sync
from onyx.access.models import ElementExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.canvas.connector import CanvasConnector
from onyx.db.models import ConnectorCredentialPair
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface

CANVAS_DOC_SYNC_TAG = "canvas_doc_sync"


def _credential_json(cc_pair: ConnectorCredentialPair) -> dict[str, Any]:
    return (
        cc_pair.credential.credential_json.get_value(apply_mask=False)
        if cc_pair.credential.credential_json
        else {}
    )


def canvas_doc_sync(
    cc_pair: ConnectorCredentialPair,
    fetch_all_existing_docs_fn: FetchAllDocumentsFunction,  # noqa: ARG001
    fetch_all_existing_docs_ids_fn: FetchAllDocumentsIdsFunction,
    callback: IndexingHeartbeatInterface | None = None,
) -> Generator[ElementExternalAccess, None, None]:
    canvas_connector = CanvasConnector(**cc_pair.connector.connector_specific_config)
    canvas_connector.load_credentials(_credential_json(cc_pair))

    yield from generic_doc_sync(
        cc_pair=cc_pair,
        fetch_all_existing_docs_ids_fn=fetch_all_existing_docs_ids_fn,
        callback=callback,
        doc_source=DocumentSource.CANVAS,
        slim_connector=canvas_connector,
        label=CANVAS_DOC_SYNC_TAG,
    )
