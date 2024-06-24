import contextlib
import time
from collections.abc import Generator
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_
from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine.util import TransactionalContext
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from danswer.configs.constants import DEFAULT_BOOST
from danswer.db.feedback import delete_document_feedback_for_documents__no_commit
from danswer.db.models import ConnectorCredentialPair
from danswer.db.models import Credential
from danswer.db.models import Document as DbDocument
from danswer.db.models import DocumentByConnectorCredentialPair
from danswer.db.tag import delete_document_tags_for_documents__no_commit
from danswer.db.utils import model_to_dict
from danswer.document_index.interfaces import DocumentMetadata
from danswer.server.documents.models import ConnectorCredentialPairIdentifier
from danswer.utils.logger import setup_logger

logger = setup_logger()


def get_documents_for_connector_credential_pair(
    db_session: Session, connector_id: int, credential_id: int, limit: int | None = None
) -> Sequence[DbDocument]:
    initial_doc_ids_stmt = select(DocumentByConnectorCredentialPair.id).where(
        and_(
            DocumentByConnectorCredentialPair.connector_id == connector_id,
            DocumentByConnectorCredentialPair.credential_id == credential_id,
        )
    )
    stmt = select(DbDocument).where(DbDocument.id.in_(initial_doc_ids_stmt)).distinct()
    if limit:
        stmt = stmt.limit(limit)
    return db_session.scalars(stmt).all()


def get_documents_by_ids(
    document_ids: list[str],
    db_session: Session,
) -> list[DbDocument]:
    stmt = select(DbDocument).where(DbDocument.id.in_(document_ids))
    documents = db_session.execute(stmt).scalars().all()
    return list(documents)


def get_document_connector_cnts(
    db_session: Session,
    document_ids: list[str],
) -> Sequence[tuple[str, int]]:
    stmt = (
        select(
            DocumentByConnectorCredentialPair.id,
            func.count(),
        )
        .where(DocumentByConnectorCredentialPair.id.in_(document_ids))
        .group_by(DocumentByConnectorCredentialPair.id)
    )
    return db_session.execute(stmt).all()  # type: ignore


def get_document_cnts_for_cc_pairs(
    db_session: Session, cc_pair_identifiers: list[ConnectorCredentialPairIdentifier]
) -> Sequence[tuple[int, int, int]]:
    stmt = (
        select(
            DocumentByConnectorCredentialPair.connector_id,
            DocumentByConnectorCredentialPair.credential_id,
            func.count(),
        )
        .where(
            or_(
                *[
                    and_(
                        DocumentByConnectorCredentialPair.connector_id
                        == cc_pair_identifier.connector_id,
                        DocumentByConnectorCredentialPair.credential_id
                        == cc_pair_identifier.credential_id,
                    )
                    for cc_pair_identifier in cc_pair_identifiers
                ]
            )
        )
        .group_by(
            DocumentByConnectorCredentialPair.connector_id,
            DocumentByConnectorCredentialPair.credential_id,
        )
    )

    return db_session.execute(stmt).all()  # type: ignore


def get_acccess_info_for_documents(
    db_session: Session,
    document_ids: list[str],
    cc_pair_to_delete: ConnectorCredentialPairIdentifier | None = None,
) -> Sequence[tuple[str, list[UUID | None], bool]]:
    """Gets back all relevant access info for the given documents. This includes
    the user_ids for cc pairs that the document is associated with + whether any
    of the associated cc pairs are intending to make the document globally public.

    If `cc_pair_to_delete` is specified, gets the above access info as if that
    pair had been deleted. This is needed since we want to delete from the Vespa
    before deleting from Postgres to ensure that the state of Postgres never "loses"
    documents that still exist in Vespa.
    """
    stmt = select(
        DocumentByConnectorCredentialPair.id,
        func.array_agg(Credential.user_id).label("user_ids"),
        func.bool_or(ConnectorCredentialPair.is_public).label("public_doc"),
    ).where(DocumentByConnectorCredentialPair.id.in_(document_ids))

    # pretend that the specified cc pair doesn't exist
    if cc_pair_to_delete:
        stmt = stmt.where(
            and_(
                DocumentByConnectorCredentialPair.connector_id
                != cc_pair_to_delete.connector_id,
                DocumentByConnectorCredentialPair.credential_id
                != cc_pair_to_delete.credential_id,
            )
        )

    stmt = (
        stmt.join(
            Credential,
            DocumentByConnectorCredentialPair.credential_id == Credential.id,
        )
        .join(
            ConnectorCredentialPair,
            and_(
                DocumentByConnectorCredentialPair.connector_id
                == ConnectorCredentialPair.connector_id,
                DocumentByConnectorCredentialPair.credential_id
                == ConnectorCredentialPair.credential_id,
            ),
        )
        .group_by(DocumentByConnectorCredentialPair.id)
    )
    return db_session.execute(stmt).all()  # type: ignore


def upsert_documents(
    db_session: Session,
    document_metadata_batch: list[DocumentMetadata],
    initial_boost: int = DEFAULT_BOOST,
) -> None:
    """NOTE: this function is Postgres specific. Not all DBs support the ON CONFLICT clause.
    Also note, this function should not be used for updating documents, only creating and
    ensuring that it exists. It IGNORES the doc_updated_at field"""
    seen_documents: dict[str, DocumentMetadata] = {}
    for document_metadata in document_metadata_batch:
        doc_id = document_metadata.document_id
        if doc_id not in seen_documents:
            seen_documents[doc_id] = document_metadata

    if not seen_documents:
        logger.info("No documents to upsert. Skipping.")
        return

    insert_stmt = insert(DbDocument).values(
        [
            model_to_dict(
                DbDocument(
                    id=doc.document_id,
                    from_ingestion_api=doc.from_ingestion_api,
                    boost=initial_boost,
                    hidden=False,
                    semantic_id=doc.semantic_identifier,
                    link=doc.first_link,
                    doc_updated_at=None,  # this is intentional
                    primary_owners=doc.primary_owners,
                    secondary_owners=doc.secondary_owners,
                )
            )
            for doc in seen_documents.values()
        ]
    )
    # for now, there are no columns to update. If more metadata is added, then this
    # needs to change to an `on_conflict_do_update`
    on_conflict_stmt = insert_stmt.on_conflict_do_nothing()
    db_session.execute(on_conflict_stmt)
    db_session.commit()


def upsert_document_by_connector_credential_pair(
    db_session: Session, document_metadata_batch: list[DocumentMetadata]
) -> None:
    """NOTE: this function is Postgres specific. Not all DBs support the ON CONFLICT clause."""
    if not document_metadata_batch:
        logger.info("`document_metadata_batch` is empty. Skipping.")
        return

    insert_stmt = insert(DocumentByConnectorCredentialPair).values(
        [
            model_to_dict(
                DocumentByConnectorCredentialPair(
                    id=document_metadata.document_id,
                    connector_id=document_metadata.connector_id,
                    credential_id=document_metadata.credential_id,
                )
            )
            for document_metadata in document_metadata_batch
        ]
    )
    # for now, there are no columns to update. If more metadata is added, then this
    # needs to change to an `on_conflict_do_update`
    on_conflict_stmt = insert_stmt.on_conflict_do_nothing()
    db_session.execute(on_conflict_stmt)
    db_session.commit()


def update_docs_updated_at(
    ids_to_new_updated_at: dict[str, datetime],
    db_session: Session,
) -> None:
    doc_ids = list(ids_to_new_updated_at.keys())
    documents_to_update = (
        db_session.query(DbDocument).filter(DbDocument.id.in_(doc_ids)).all()
    )

    for document in documents_to_update:
        document.doc_updated_at = ids_to_new_updated_at[document.id]

    db_session.commit()


def upsert_documents_complete(
    db_session: Session,
    document_metadata_batch: list[DocumentMetadata],
) -> None:
    upsert_documents(db_session, document_metadata_batch)
    upsert_document_by_connector_credential_pair(db_session, document_metadata_batch)
    logger.info(
        f"Upserted {len(document_metadata_batch)} document store entries into DB"
    )


def delete_document_by_connector_credential_pair__no_commit(
    db_session: Session,
    document_ids: list[str],
    connector_credential_pair_identifier: ConnectorCredentialPairIdentifier
    | None = None,
) -> None:
    stmt = delete(DocumentByConnectorCredentialPair).where(
        DocumentByConnectorCredentialPair.id.in_(document_ids)
    )
    if connector_credential_pair_identifier:
        stmt = stmt.where(
            and_(
                DocumentByConnectorCredentialPair.connector_id
                == connector_credential_pair_identifier.connector_id,
                DocumentByConnectorCredentialPair.credential_id
                == connector_credential_pair_identifier.credential_id,
            )
        )
    db_session.execute(stmt)


def delete_documents__no_commit(db_session: Session, document_ids: list[str]) -> None:
    db_session.execute(delete(DbDocument).where(DbDocument.id.in_(document_ids)))


def delete_documents_complete__no_commit(
    db_session: Session, document_ids: list[str]
) -> None:
    logger.info(f"Deleting {len(document_ids)} documents from the DB")
    delete_document_by_connector_credential_pair__no_commit(db_session, document_ids)
    delete_document_feedback_for_documents__no_commit(
        document_ids=document_ids, db_session=db_session
    )
    delete_document_tags_for_documents__no_commit(
        document_ids=document_ids, db_session=db_session
    )
    delete_documents__no_commit(db_session, document_ids)


def acquire_document_locks(db_session: Session, document_ids: list[str]) -> bool:
    """Acquire locks for the specified documents. Ideally this shouldn't be
    called with large list of document_ids (an exception could be made if the
    length of holding the lock is very short).

    Will simply raise an exception if any of the documents are already locked.
    This prevents deadlocks (assuming that the caller passes in all required
    document IDs in a single call).
    """
    stmt = (
        select(DbDocument.id)
        .where(DbDocument.id.in_(document_ids))
        .with_for_update(nowait=True)
    )
    # will raise exception if any of the documents are already locked
    documents = db_session.scalars(stmt).all()

    # make sure we found every document
    if len(documents) != len(set(document_ids)):
        logger.warning("Didn't find row for all specified document IDs. Aborting.")
        return False

    return True


_NUM_LOCK_ATTEMPTS = 10
_LOCK_RETRY_DELAY = 30


@contextlib.contextmanager
def prepare_to_modify_documents(
    db_session: Session, document_ids: list[str], retry_delay: int = _LOCK_RETRY_DELAY
) -> Generator[TransactionalContext, None, None]:
    """Try and acquire locks for the documents to prevent other jobs from
    modifying them at the same time (e.g. avoid race conditions). This should be
    called ahead of any modification to Vespa. Locks should be released by the
    caller as soon as updates are complete by finishing the transaction.

    NOTE: only one commit is allowed within the context manager returned by this funtion.
    Multiple commits will result in a sqlalchemy.exc.InvalidRequestError.
    NOTE: this function will commit any existing transaction.
    """

    db_session.commit()  # ensure that we're not in a transaction

    lock_acquired = False
    for _ in range(_NUM_LOCK_ATTEMPTS):
        try:
            with db_session.begin() as transaction:
                lock_acquired = acquire_document_locks(
                    db_session=db_session, document_ids=document_ids
                )
                if lock_acquired:
                    yield transaction
                    break
        except OperationalError as e:
            logger.info(f"Failed to acquire locks for documents, retrying. Error: {e}")

        time.sleep(retry_delay)

    if not lock_acquired:
        raise RuntimeError(
            f"Failed to acquire locks after {_NUM_LOCK_ATTEMPTS} attempts "
            f"for documents: {document_ids}"
        )


def get_ingestion_documents(
    db_session: Session,
) -> list[DbDocument]:
    # TODO add the option to filter by DocumentSource
    stmt = select(DbDocument).where(DbDocument.from_ingestion_api.is_(True))
    documents = db_session.execute(stmt).scalars().all()
    return list(documents)


def get_documents_by_cc_pair(
    cc_pair_id: int,
    db_session: Session,
) -> list[DbDocument]:
    return (
        db_session.query(DbDocument)
        .join(
            DocumentByConnectorCredentialPair,
            DbDocument.id == DocumentByConnectorCredentialPair.id,
        )
        .join(
            ConnectorCredentialPair,
            and_(
                DocumentByConnectorCredentialPair.connector_id
                == ConnectorCredentialPair.connector_id,
                DocumentByConnectorCredentialPair.credential_id
                == ConnectorCredentialPair.credential_id,
            ),
        )
        .filter(ConnectorCredentialPair.id == cc_pair_id)
        .all()
    )
