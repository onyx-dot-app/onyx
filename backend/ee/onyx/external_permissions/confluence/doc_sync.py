"""
Rules defined here:
https://confluence.atlassian.com/conf85/check-who-can-view-a-page-1283360557.html
"""

from collections.abc import Generator

from ee.onyx.external_permissions.perm_sync_types import FetchAllDocumentsFunction
from ee.onyx.external_permissions.perm_sync_types import FetchAllDocumentsIdsFunction
from ee.onyx.external_permissions.utils import generic_doc_sync
from onyx.access.models import DocExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.confluence.access import get_all_space_permissions
from onyx.connectors.confluence.connector import ConfluenceConnector
from onyx.connectors.credentials_provider import OnyxDBCredentialsProvider
from onyx.db.models import ConnectorCredentialPair
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


CONFLUENCE_DOC_SYNC_LABEL = "confluence_doc_sync"


def confluence_doc_sync(
    cc_pair: ConnectorCredentialPair,
    fetch_all_existing_docs_fn: FetchAllDocumentsFunction,
    fetch_all_existing_docs_ids_fn: FetchAllDocumentsIdsFunction,
    callback: IndexingHeartbeatInterface | None,
) -> Generator[DocExternalAccess, None, None]:
    """
    Fetches document permissions from Confluence and yields DocExternalAccess objects.
    Compares fetched documents against existing documents in the DB for the connector.
    If a document exists in the DB but not in the Confluence fetch, it's marked as restricted.
    """

    # get space level access info
    confluence_client_for_space_level_access = ConfluenceConnector(
        **cc_pair.connector.connector_specific_config,
    )
    space_level_access_info = get_all_space_permissions(
        confluence_client_for_space_level_access.confluence_client,
        confluence_client_for_space_level_access.is_cloud,
    )
    if not space_level_access_info:
        raise ValueError(
            "No space level access info found. Likely missing "
            "permissions to retrieve spaces/space permissions."
        )

    # get doc level access info
    confluence_connector = ConfluenceConnector(
        **cc_pair.connector.connector_specific_config,
        space_level_access_info=space_level_access_info,
    )

    provider = OnyxDBCredentialsProvider(
        get_current_tenant_id(), "confluence", cc_pair.credential_id
    )
    confluence_connector.set_credentials_provider(provider)

    yield from generic_doc_sync(
        cc_pair=cc_pair,
        fetch_all_existing_docs_ids_fn=fetch_all_existing_docs_ids_fn,
        callback=callback,
        doc_source=DocumentSource.CONFLUENCE,
        slim_connector=confluence_connector,
        label=CONFLUENCE_DOC_SYNC_LABEL,
    )
