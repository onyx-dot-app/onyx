from collections.abc import Generator

from ee.onyx.external_permissions.perm_sync_types import (
    FetchAllDocumentsFunction,
    FetchAllDocumentsIdsFunction,
)
from ee.onyx.external_permissions.utils import credential_json, generic_doc_sync
from onyx.access.models import ElementExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.teams.connector import TeamsConnector, is_thread_document_id
from onyx.db.models import ConnectorCredentialPair
from onyx.db.utils import DocumentRow
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()


TEAMS_DOC_SYNC_LABEL = "teams_doc_sync"


def _names_people_and_no_group(row: DocumentRow) -> bool:
    """A thread an older version indexed carries member emails and no group.
    A thread whose access an earlier sync emptied carries neither and is left
    to pruning, so it does not bring the thread walk back."""
    return (
        is_thread_document_id(row.id)
        and not row.external_user_group_ids
        and bool(row.external_user_emails)
    )


def teams_doc_sync(
    cc_pair: ConnectorCredentialPair,
    fetch_all_existing_docs_fn: FetchAllDocumentsFunction,
    fetch_all_existing_docs_ids_fn: FetchAllDocumentsIdsFunction,  # noqa: ARG001
    callback: IndexingHeartbeatInterface | None,
) -> Generator[ElementExternalAccess, None, None]:
    """A thread names its channel's group for good and the group sync says who
    is in it, so reading threads again changes nothing. They are read only while
    an indexed one still names people instead, as one from an older version
    does. The rows are read once and answer both that and what the walk covers."""
    rows = fetch_all_existing_docs_fn(sort_order=None)
    lists_threads = any(_names_people_and_no_group(row) for row in rows)

    teams_connector = TeamsConnector(
        **cc_pair.connector.connector_specific_config,
    )
    teams_connector.load_credentials(credential_json(cc_pair))
    if lists_threads:
        logger.info("Some indexed threads name no group yet, so threads are read")
    else:
        teams_connector.skip_threads_in_perm_sync()

    def existing_ids_this_walk_covers() -> list[str]:
        # The sync empties the access of a document the walk did not list, so
        # the threads it leaves alone are not offered to it.
        return [
            row.id for row in rows if lists_threads or not is_thread_document_id(row.id)
        ]

    yield from generic_doc_sync(
        cc_pair=cc_pair,
        fetch_all_existing_docs_ids_fn=existing_ids_this_walk_covers,
        callback=callback,
        doc_source=DocumentSource.TEAMS,
        slim_connector=teams_connector,
        label=TEAMS_DOC_SYNC_LABEL,
    )
