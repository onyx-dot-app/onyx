from collections.abc import Generator

from ee.onyx.external_permissions.perm_sync_types import FetchAllDocumentsFunction
from ee.onyx.external_permissions.perm_sync_types import FetchAllDocumentsIdsFunction
from ee.onyx.external_permissions.utils import generic_doc_sync
from onyx.access.models import ElementExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.db.models import ConnectorCredentialPair
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

JSM_DOC_SYNC_TAG = "jira_service_management_doc_sync"


def jira_service_management_doc_sync(
    cc_pair: ConnectorCredentialPair,
    fetch_all_existing_docs_fn: FetchAllDocumentsFunction,  # noqa: ARG001
    fetch_all_existing_docs_ids_fn: FetchAllDocumentsIdsFunction,
    callback: IndexingHeartbeatInterface | None = None,
) -> Generator[ElementExternalAccess, None, None]:
    config = cc_pair.connector.connector_specific_config
    jsm_connector = JiraServiceManagementConnector(
        jira_service_management_base_url=config.get("jira_service_management_base_url", ""),
        project_key=config.get("project_key"),
        comment_email_blacklist=config.get("comment_email_blacklist"),
        labels_to_skip=config.get("labels_to_skip", []),
        jql_query=config.get("jql_query"),
        scoped_token=config.get("scoped_token", False),
    )
    credential_json = (
        cc_pair.credential.credential_json.get_value(apply_mask=False)
        if cc_pair.credential.credential_json
        else {}
    )
    jsm_connector.load_credentials(credential_json)

    yield from generic_doc_sync(
        cc_pair=cc_pair,
        fetch_all_existing_docs_ids_fn=fetch_all_existing_docs_ids_fn,
        callback=callback,
        doc_source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
        slim_connector=jsm_connector,
        label=JSM_DOC_SYNC_TAG,
    )
