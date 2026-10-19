"""JSM permission sync: same Jira gateway, distinct document source."""

from collections.abc import Generator

from ee.onyx.external_permissions.perm_sync_types import (
    FetchAllDocumentsFunction,
    FetchAllDocumentsIdsFunction,
)
from ee.onyx.external_permissions.utils import credential_json, generic_doc_sync
from onyx.access.models import ElementExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.factory import build_connector_kwargs
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.db.models import ConnectorCredentialPair
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface

JSM_DOC_SYNC_TAG = "jsm_doc_sync"


def jsm_doc_sync(
    cc_pair: ConnectorCredentialPair,
    fetch_all_existing_docs_fn: FetchAllDocumentsFunction,  # noqa: ARG001
    fetch_all_existing_docs_ids_fn: FetchAllDocumentsIdsFunction,
    callback: IndexingHeartbeatInterface | None = None,
) -> Generator[ElementExternalAccess, None, None]:
    """Enumerate JSM tickets and attachments using the actual JSM connector.

    Do not build a plain JiraConnector: that would omit attachment slim IDs and
    could incorrectly revoke permissions for JSM documents during sync.
    """
    connector = JiraServiceManagementConnector(
        **build_connector_kwargs(
            cc_pair.connector.source, cc_pair.connector.connector_specific_config
        ),
    )
    connector.load_credentials(credential_json(cc_pair))

    yield from generic_doc_sync(
        cc_pair=cc_pair,
        fetch_all_existing_docs_ids_fn=fetch_all_existing_docs_ids_fn,
        callback=callback,
        doc_source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
        slim_connector=connector,
        label=JSM_DOC_SYNC_TAG,
    )
