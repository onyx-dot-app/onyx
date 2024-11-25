from datetime import datetime
from datetime import timezone

from sqlalchemy.orm import Session

from danswer.access.models import ExternalAccess
from danswer.connectors.gmail.connector import GmailConnector
from danswer.connectors.interfaces import GenerateSlimDocumentOutput
from danswer.db.models import ConnectorCredentialPair
from danswer.db.users import batch_add_non_web_user_if_not_exists__no_commit
from danswer.utils.logger import setup_logger
from ee.danswer.db.document import upsert_document_external_perms__no_commit

logger = setup_logger()


def _get_slim_doc_generator(
    cc_pair: ConnectorCredentialPair,
    gmail_connector: GmailConnector,
) -> GenerateSlimDocumentOutput:
    current_time = datetime.now(timezone.utc)
    start_time = (
        cc_pair.last_time_perm_sync.replace(tzinfo=timezone.utc).timestamp()
        if cc_pair.last_time_perm_sync
        else 0.0
    )

    return gmail_connector.retrieve_all_slim_documents(
        start=start_time, end=current_time.timestamp()
    )


def gmail_doc_sync(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
) -> None:
    """
    Adds the external permissions to the documents in postgres
    if the document doesn't already exists in postgres, we create
    it in postgres so that when it gets created later, the permissions are
    already populated
    """
    gmail_connector = GmailConnector(**cc_pair.connector.connector_specific_config)
    gmail_connector.load_credentials(cc_pair.credential.credential_json)

    slim_doc_generator = _get_slim_doc_generator(cc_pair, gmail_connector)

    for slim_doc_batch in slim_doc_generator:
        for slim_doc in slim_doc_batch:
            if slim_doc.perm_sync_data is None:
                logger.warning(f"No permissions found for document {slim_doc.id}")
                continue
            if user_email := slim_doc.perm_sync_data.get("user_email"):
                ext_access = ExternalAccess(
                    external_user_emails=set([user_email]),
                    external_user_group_ids=set(),
                    is_public=False,
                )
                batch_add_non_web_user_if_not_exists__no_commit(
                    db_session=db_session,
                    emails=list(ext_access.external_user_emails),
                )
                upsert_document_external_perms__no_commit(
                    db_session=db_session,
                    doc_id=slim_doc.id,
                    external_access=ext_access,
                    source_type=cc_pair.connector.source,
                )
