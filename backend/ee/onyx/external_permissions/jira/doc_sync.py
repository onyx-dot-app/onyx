from collections.abc import Generator

from ee.onyx.external_permissions.perm_sync_types import (
    FetchAllDocumentsFunction,
    FetchAllDocumentsIdsFunction,
)
from ee.onyx.external_permissions.utils import credential_json, generic_doc_sync
from onyx.access.models import ElementExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import JiraConnector
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
    jira_connector = JiraConnector(
        **cc_pair.connector.connector_specific_config,
    )
    jira_connector.load_credentials(credential_json(cc_pair))

    yield from generic_doc_sync(
        cc_pair=cc_pair,
        fetch_all_existing_docs_ids_fn=fetch_all_existing_docs_ids_fn,
        callback=callback,
        doc_source=DocumentSource.JIRA,
        slim_connector=jira_connector,
        label=JIRA_DOC_SYNC_TAG,
    )
