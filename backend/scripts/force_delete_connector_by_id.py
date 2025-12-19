import argparse
import os
import sys

from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.db.document import delete_documents_complete__no_commit
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.search_settings import get_active_search_settings
from onyx.db.tag import delete_orphan_tags__no_commit
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA

# Modify sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

# pylint: disable=E402
# flake8: noqa: E402

# Now import Onyx modules
from onyx.db.models import (
    DocumentSet__ConnectorCredentialPair,
    UserGroup__ConnectorCredentialPair,
)
from onyx.db.connector import fetch_connector_by_id
from onyx.db.document import get_documents_for_connector_credential_pair
from onyx.db.index_attempt import (
    delete_index_attempts,
    cancel_indexing_attempts_for_ccpair,
)
from onyx.db.permission_sync_attempt import (
    delete_doc_permission_sync_attempts__no_commit,
)
from onyx.db.permission_sync_attempt import (
    delete_external_group_permission_sync_attempts__no_commit,
)
from onyx.db.models import ConnectorCredentialPair
from onyx.document_index.interfaces import DocumentIndex
from onyx.utils.logger import setup_logger
from onyx.configs.constants import DocumentSource
from onyx.db.connector_credential_pair import (
    get_connector_credential_pair_from_id,
    get_connector_credential_pair,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.document_index.factory import get_default_document_index
from onyx.file_store.file_store import get_default_file_store

# pylint: enable=E402
# flake8: noqa: E402


logger = setup_logger()

_DELETION_BATCH_SIZE = 1000


def _unsafe_deletion(
    db_session: Session,
    document_index: DocumentIndex,
    cc_pair: ConnectorCredentialPair,
    pair_id: int,
) -> int:
    connector_id = cc_pair.connector_id
    credential_id = cc_pair.credential_id

    num_docs_deleted = 0

    # Gather and delete documents
    while True:
        documents = get_documents_for_connector_credential_pair(
            db_session=db_session,
            connector_id=connector_id,
            credential_id=credential_id,
            limit=_DELETION_BATCH_SIZE,
        )
        if not documents:
            break

        for document in documents:
            document_index.delete_single(
                doc_id=document.id,
                tenant_id=POSTGRES_DEFAULT_SCHEMA,
                chunk_count=document.chunk_count,
            )

        delete_documents_complete__no_commit(
            db_session=db_session,
            document_ids=[document.id for document in documents],
        )
        delete_orphan_tags__no_commit(db_session=db_session)

        num_docs_deleted += len(documents)

    # Delete index attempts
    delete_index_attempts(
        db_session=db_session,
        cc_pair_id=cc_pair.id,
    )

    # Delete permission sync attempts
    delete_doc_permission_sync_attempts__no_commit(
        db_session=db_session,
        cc_pair_id=cc_pair.id,
    )
    delete_external_group_permission_sync_attempts__no_commit(
        db_session=db_session,
        cc_pair_id=cc_pair.id,
    )

    # Delete document sets
    stmt = delete(DocumentSet__ConnectorCredentialPair).where(
        DocumentSet__ConnectorCredentialPair.connector_credential_pair_id == pair_id
    )
    db_session.execute(stmt)

    # delete user group associations
    stmt = delete(UserGroup__ConnectorCredentialPair).where(
        UserGroup__ConnectorCredentialPair.cc_pair_id == pair_id
    )
    db_session.execute(stmt)

    # need to flush to avoid foreign key violations
    db_session.flush()

    # delete the actual connector credential pair
    stmt = delete(ConnectorCredentialPair).where(
        ConnectorCredentialPair.connector_id == connector_id,
        ConnectorCredentialPair.credential_id == credential_id,
    )
    db_session.execute(stmt)

    # Delete Connector
    connector = fetch_connector_by_id(
        db_session=db_session,
        connector_id=connector_id,
    )
    if not connector or not len(connector.credentials):
        logger.debug("Found no credentials left for connector, deleting connector")
        db_session.delete(connector)
    db_session.commit()

    logger.notice(
        "Successfully deleted connector_credential_pair with connector_id:"
        f" '{connector_id}' and credential_id: '{credential_id}'. Deleted {num_docs_deleted} docs."
    )
    return num_docs_deleted


def _delete_connector(cc_pair_id: int, db_session: Session) -> None:
    user_input = input(
        "DO NOT USE THIS UNLESS YOU KNOW WHAT YOU ARE DOING. \
        IT MAY CAUSE ISSUES with your Onyx instance! \
        Are you SURE you want to continue? (enter 'Y' to continue): "
    )
    if user_input != "Y":
        logger.notice(f"You entered {user_input}. Exiting!")
        return

    logger.notice("Getting connector credential pair")
    cc_pair = get_connector_credential_pair_from_id(
        db_session=db_session,
        cc_pair_id=cc_pair_id,
    )

    if not cc_pair:
        logger.error(f"Connector credential pair with ID {cc_pair_id} not found")
        return

    if cc_pair.status == ConnectorCredentialPairStatus.ACTIVE:
        logger.error(
            f"Connector {cc_pair.connector.name} is active, cannot continue. \
            Please navigate to the connector and pause before attempting again"
        )
        return

    connector_id = cc_pair.connector_id
    credential_id = cc_pair.credential_id

    if cc_pair is None:
        logger.error(
            f"Connector with ID '{connector_id}' and credential ID "
            f"'{credential_id}' does not exist. Has it already been deleted?",
        )
        return

    logger.notice("Cancelling indexing attempt for the connector")
    cancel_indexing_attempts_for_ccpair(
        cc_pair_id=cc_pair_id, db_session=db_session, include_secondary_index=True
    )

    validated_cc_pair = get_connector_credential_pair(
        db_session=db_session,
        connector_id=connector_id,
        credential_id=credential_id,
    )

    if not validated_cc_pair:
        logger.error(
            f"Cannot run deletion attempt - connector_credential_pair with Connector ID: "
            f"{connector_id} and Credential ID: {credential_id} does not exist."
        )

    file_ids: list[str] = (
        cc_pair.connector.connector_specific_config["file_locations"]
        if cc_pair.connector.source == DocumentSource.FILE
        else []
    )
    try:
        logger.notice("Deleting information from Vespa and Postgres")
        active_search_settings = get_active_search_settings(db_session)
        document_index = get_default_document_index(
            active_search_settings.primary,
            active_search_settings.secondary,
        )

        files_deleted_count = _unsafe_deletion(
            db_session=db_session,
            document_index=document_index,
            cc_pair=cc_pair,
            pair_id=cc_pair_id,
        )
        logger.notice(f"Deleted {files_deleted_count} files!")

    except Exception as e:
        logger.error(f"Failed to delete connector due to {e}")

    if file_ids:
        logger.notice("Deleting stored files!")
        file_store = get_default_file_store()
        for file_id in file_ids:
            logger.notice(f"Deleting file {file_id}")
            file_store.delete_file(file_id)

    db_session.commit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Delete a connector by its ID")
    parser.add_argument(
        "connector_id", type=int, help="The ID of the connector to delete"
    )

    args = parser.parse_args()
    with get_session_with_current_tenant() as db_session:
        _delete_connector(args.connector_id, db_session)
