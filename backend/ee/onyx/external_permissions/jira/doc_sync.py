from collections.abc import Generator

from ee.onyx.external_permissions.perm_sync_types import (
    FetchAllDocumentsFunction,
    FetchAllDocumentsIdsFunction,
)
from ee.onyx.external_permissions.utils import credential_json, generic_doc_sync
from onyx.access.models import ElementExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.factory import build_connector_kwargs
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.db.models import ConnectorCredentialPair
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

JIRA_DOC_SYNC_TAG = "jira_doc_sync"


def jira_doc_sync(
    cc_pair: ConnectorCredentialPair,
    fetch_all_existing_docs_fn: FetchAllDocumentsFunction,  # noqa: ARG001
    fetch_all_existing_docs_ids_fn: FetchAllDocumentsIdsFunction,
    callback: IndexingHeartbeatInterface | None = None,
) -> Generator[ElementExternalAccess, None, None]:
    is_jsm = cc_pair.connector.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    connector_cls = JiraServiceManagementConnector if is_jsm else JiraConnector
    doc_source = (
        DocumentSource.JIRA_SERVICE_MANAGEMENT if is_jsm else DocumentSource.JIRA
    )
    jira_connector = connector_cls(
        **build_connector_kwargs(
            doc_source, cc_pair.connector.connector_specific_config
        ),
    )
    jira_connector.load_credentials(credential_json(cc_pair))

    yield from generic_doc_sync(
        cc_pair=cc_pair,
        fetch_all_existing_docs_ids_fn=fetch_all_existing_docs_ids_fn,
        callback=callback,
        doc_source=doc_source,
        slim_connector=jira_connector,
        label=JIRA_DOC_SYNC_TAG,
    )
