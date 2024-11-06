import argparse
import os
import sys

from sqlalchemy import delete
from sqlalchemy.orm import Session

from danswer.db.enums import ConnectorCredentialPairStatus

# Modify sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

# pylint: disable=E402
# flake8: noqa: E402

# Now import Danswer modules
from danswer.db.models import (
    DocumentSet__ConnectorCredentialPair,
    UserGroup__ConnectorCredentialPair,
)
from danswer.db.connector import fetch_connector_by_id
from danswer.db.document import get_documents_for_connector_credential_pair
from danswer.db.index_attempt import (
    delete_index_attempts,
    cancel_indexing_attempts_for_ccpair,
)
from danswer.db.models import ConnectorCredentialPair
from danswer.document_index.interfaces import DocumentIndex
from danswer.utils.logger import setup_logger
from danswer.configs.constants import DocumentSource
from danswer.db.connector_credential_pair import (
    get_connector_credential_pair_from_id,
    get_connector_credential_pair,
)
from danswer.db.engine import get_session_context_manager
from danswer.document_index.factory import get_default_document_index
from danswer.file_store.file_store import get_default_file_store
from danswer.document_index.document_index_utils import get_both_index_names
from danswer.db.document import delete_documents_complete__no_commit

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

        document_ids = [document.id for document in documents]
        document_index.delete(doc_ids=document_ids)
        delete_documents_complete__no_commit(
            db_session=db_session,
            document_ids=document_ids,
        )

        num_docs_deleted += len(documents)

    # Delete index attempts
    delete_index_attempts(
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
        IT MAY CAUSE ISSUES with your Danswer instance! \
        Are you SURE you want to continue? (enter 'Y' to continue): "
    )
    if user_input != "Y":
        logger.notice(f"You entered {user_input}. Exiting!")
        return

    logger.notice("Getting connector credential pair")
    cc_pair = get_connector_credential_pair_from_id(cc_pair_id, db_session)

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

    file_names: list[str] = (
        cc_pair.connector.connector_specific_config["file_locations"]
        if cc_pair.connector.source == DocumentSource.FILE
        else []
    )
    try:
        logger.notice("Deleting information from Vespa and Postgres")
        curr_ind_name, sec_ind_name = get_both_index_names(db_session)
        document_index = get_default_document_index(
            primary_index_name=curr_ind_name, secondary_index_name=sec_ind_name
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

    if file_names:
        logger.notice("Deleting stored files!")
        file_store = get_default_file_store(db_session)
        for file_name in file_names:
            logger.notice(f"Deleting file {file_name}")
            file_store.delete_file(file_name)

    db_session.commit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Delete a connector by its ID")
    parser.add_argument(
        "connector_id", type=int, help="The ID of the connector to delete"
    )
    args = parser.parse_args()
    with get_session_context_manager() as db_session:
        _delete_connector(args.connector_id, db_session)
