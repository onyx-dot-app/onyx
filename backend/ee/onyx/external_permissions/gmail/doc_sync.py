from datetime import datetime
from datetime import timezone

from onyx.access.models import DocExternalAccess
from onyx.access.models import ExternalAccess
from onyx.connectors.gmail.connector import GmailConnector
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.db.models import ConnectorCredentialPair
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _get_slim_doc_generator(
    cc_pair: ConnectorCredentialPair,
    gmail_connector: GmailConnector,
    callback: IndexingHeartbeatInterface | None = None,
) -> GenerateSlimDocumentOutput:
    current_time = datetime.now(timezone.utc)
    start_time = (
        cc_pair.last_time_perm_sync.replace(tzinfo=timezone.utc).timestamp()
        if cc_pair.last_time_perm_sync
        else 0.0
    )

    return gmail_connector.retrieve_all_slim_documents(
        start=start_time,
        end=current_time.timestamp(),
        callback=callback,
    )


def gmail_doc_sync(
    cc_pair: ConnectorCredentialPair, callback: IndexingHeartbeatInterface | None
) -> list[DocExternalAccess]:
    """
    Adds the external permissions to the documents in postgres
    if the document doesn't already exists in postgres, we create
    it in postgres so that when it gets created later, the permissions are
    already populated
    """
    gmail_connector = GmailConnector(**cc_pair.connector.connector_specific_config)
    gmail_connector.load_credentials(cc_pair.credential.credential_json)

    slim_doc_generator = _get_slim_doc_generator(
        cc_pair, gmail_connector, callback=callback
    )

    document_external_access: list[DocExternalAccess] = []
    for slim_doc_batch in slim_doc_generator:
        for slim_doc in slim_doc_batch:
            if callback:
                if callback.should_stop():
                    raise RuntimeError("gmail_doc_sync: Stop signal detected")

                callback.progress("gmail_doc_sync", 1)

            if slim_doc.perm_sync_data is None:
                logger.warning(f"No permissions found for document {slim_doc.id}")
                continue
            if user_email := slim_doc.perm_sync_data.get("user_email"):
                ext_access = ExternalAccess(
                    external_user_emails=set([user_email]),
                    external_user_group_ids=set(),
                    is_public=False,
                )
                document_external_access.append(
                    DocExternalAccess(
                        doc_id=slim_doc.id,
                        external_access=ext_access,
                    )
                )

    return document_external_access
