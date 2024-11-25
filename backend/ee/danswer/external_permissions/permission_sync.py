from datetime import datetime
from datetime import timezone

from sqlalchemy.orm import Session

from danswer.access.access import get_access_for_documents
from danswer.db.connector_credential_pair import get_connector_credential_pair_from_id
from danswer.db.document import get_document_ids_for_connector_credential_pair
from danswer.document_index.factory import get_current_primary_default_document_index
from danswer.document_index.interfaces import UpdateRequest
from danswer.utils.logger import setup_logger
from ee.danswer.external_permissions.sync_params import DOC_PERMISSIONS_FUNC_MAP
from ee.danswer.external_permissions.sync_params import GROUP_PERMISSIONS_FUNC_MAP

logger = setup_logger()


def run_external_group_permission_sync(
    db_session: Session,
    cc_pair_id: int,
) -> None:
    cc_pair = get_connector_credential_pair_from_id(cc_pair_id, db_session)
    if cc_pair is None:
        raise ValueError(f"No connector credential pair found for id: {cc_pair_id}")

    source_type = cc_pair.connector.source
    group_sync_func = GROUP_PERMISSIONS_FUNC_MAP.get(source_type)

    if group_sync_func is None:
        # Not all sync connectors support group permissions so this is fine
        return

    try:
        # This function updates:
        # - the user_email <-> external_user_group_id mapping
        # in postgres without committing
        logger.debug(f"Syncing groups for {source_type}")
        if group_sync_func is not None:
            group_sync_func(
                db_session,
                cc_pair,
            )

        # update postgres
        db_session.commit()
    except Exception:
        logger.exception("Error Syncing Group Permissions")
        db_session.rollback()


def run_external_doc_permission_sync(
    db_session: Session,
    cc_pair_id: int,
) -> None:
    cc_pair = get_connector_credential_pair_from_id(cc_pair_id, db_session)
    if cc_pair is None:
        raise ValueError(f"No connector credential pair found for id: {cc_pair_id}")

    source_type = cc_pair.connector.source

    doc_sync_func = DOC_PERMISSIONS_FUNC_MAP.get(source_type)
    last_time_perm_sync = cc_pair.last_time_perm_sync

    if doc_sync_func is None:
        raise ValueError(
            f"No permission sync function found for source type: {source_type}"
        )

    try:
        # This function updates:
        # - the user_email <-> document mapping
        # - the external_user_group_id <-> document mapping
        # in postgres without committing
        logger.info(f"Syncing docs for {source_type}")
        doc_sync_func(
            db_session,
            cc_pair,
        )

        # Get the document ids for the cc pair
        document_ids_for_cc_pair = get_document_ids_for_connector_credential_pair(
            db_session=db_session,
            connector_id=cc_pair.connector_id,
            credential_id=cc_pair.credential_id,
        )

        # This function fetches the updated access for the documents
        # and returns a dictionary of document_ids and access
        # This is the access we want to update vespa with
        docs_access = get_access_for_documents(
            document_ids=document_ids_for_cc_pair,
            db_session=db_session,
        )

        # Then we build the update requests to update vespa
        update_reqs = [
            UpdateRequest(document_ids=[doc_id], access=doc_access)
            for doc_id, doc_access in docs_access.items()
        ]

        # Don't bother sync-ing secondary, it will be sync-ed after switch anyway
        document_index = get_current_primary_default_document_index(db_session)

        # update vespa
        document_index.update(update_reqs)

        cc_pair.last_time_perm_sync = datetime.now(timezone.utc)

        # update postgres
        db_session.commit()
        logger.info(f"Successfully synced docs for {source_type}")
    except Exception:
        logger.exception("Error Syncing Document Permissions")
        cc_pair.last_time_perm_sync = last_time_perm_sync
        db_session.rollback()
