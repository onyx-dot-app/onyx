import contextlib
import time
from collections.abc import Generator
from collections.abc import Sequence
from datetime import datetime
from datetime import timezone

from sqlalchemy import and_
from sqlalchemy import delete
from sqlalchemy import exists
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import Select
from sqlalchemy import select
from sqlalchemy import tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine.util import TransactionalContext
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.sql.expression import null

from onyx.configs.constants import DEFAULT_BOOST
from onyx.configs.constants import DocumentSource
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.feedback import delete_document_feedback_for_documents__no_commit
from onyx.db.models import Connector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Credential
from onyx.db.models import Document as DbDocument
from onyx.db.models import DocumentByConnectorCredentialPair
from onyx.db.models import User
from onyx.db.tag import delete_document_tags_for_documents__no_commit
from onyx.db.utils import model_to_dict
from onyx.document_index.interfaces import DocumentMetadata
from onyx.server.documents.models import ConnectorCredentialPairIdentifier
from onyx.utils.logger import setup_logger

logger = setup_logger()


def check_docs_exist(db_session: Session) -> bool:
    stmt = select(exists(DbDocument))
    result = db_session.execute(stmt)
    return result.scalar() or False


def count_documents_by_needs_sync(session: Session) -> int:
    """Get the count of all documents where:
    1. last_modified is newer than last_synced
    2. last_synced is null (meaning we've never synced)
    AND the document has a relationship with a connector/credential pair

    TODO: The documents without a relationship with a connector/credential pair
    should be cleaned up somehow eventually.

    This function executes the query and returns the count of
    documents matching the criteria."""

    count = (
        session.query(func.count(DbDocument.id.distinct()))
        .select_from(DbDocument)
        .join(
            DocumentByConnectorCredentialPair,
            DbDocument.id == DocumentByConnectorCredentialPair.id,
        )
        .filter(
            or_(
                DbDocument.last_modified > DbDocument.last_synced,
                DbDocument.last_synced.is_(None),
            )
        )
        .scalar()
    )

    return count


def construct_document_select_for_connector_credential_pair_by_needs_sync(
    connector_id: int, credential_id: int
) -> Select:
    initial_doc_ids_stmt = select(DocumentByConnectorCredentialPair.id).where(
        and_(
            DocumentByConnectorCredentialPair.connector_id == connector_id,
            DocumentByConnectorCredentialPair.credential_id == credential_id,
        )
    )

    stmt = (
        select(DbDocument)
        .where(
            DbDocument.id.in_(initial_doc_ids_stmt),
            or_(
                DbDocument.last_modified
                > DbDocument.last_synced,  # last_modified is newer than last_synced
                DbDocument.last_synced.is_(None),  # never synced
            ),
        )
        .distinct()
    )

    return stmt


def get_all_documents_needing_vespa_sync_for_cc_pair(
    db_session: Session, cc_pair_id: int
) -> list[DbDocument]:
    cc_pair = get_connector_credential_pair_from_id(
        cc_pair_id=cc_pair_id, db_session=db_session
    )
    if not cc_pair:
        raise ValueError(f"No CC pair found with ID: {cc_pair_id}")

    stmt = construct_document_select_for_connector_credential_pair_by_needs_sync(
        cc_pair.connector_id, cc_pair.credential_id
    )

    return list(db_session.scalars(stmt).all())


def construct_document_select_for_connector_credential_pair(
    connector_id: int, credential_id: int | None = None
) -> Select:
    initial_doc_ids_stmt = select(DocumentByConnectorCredentialPair.id).where(
        and_(
            DocumentByConnectorCredentialPair.connector_id == connector_id,
            DocumentByConnectorCredentialPair.credential_id == credential_id,
        )
    )
    stmt = select(DbDocument).where(DbDocument.id.in_(initial_doc_ids_stmt)).distinct()
    return stmt


def get_documents_for_cc_pair(
    db_session: Session,
    cc_pair_id: int,
) -> list[DbDocument]:
    cc_pair = get_connector_credential_pair_from_id(
        cc_pair_id=cc_pair_id, db_session=db_session
    )
    if not cc_pair:
        raise ValueError(f"No CC pair found with ID: {cc_pair_id}")
    stmt = construct_document_select_for_connector_credential_pair(
        connector_id=cc_pair.connector_id, credential_id=cc_pair.credential_id
    )
    return list(db_session.scalars(stmt).all())


def get_document_ids_for_connector_credential_pair(
    db_session: Session, connector_id: int, credential_id: int, limit: int | None = None
) -> list[str]:
    doc_ids_stmt = select(DocumentByConnectorCredentialPair.id).where(
        and_(
            DocumentByConnectorCredentialPair.connector_id == connector_id,
            DocumentByConnectorCredentialPair.credential_id == credential_id,
        )
    )
    return list(db_session.execute(doc_ids_stmt).scalars().all())


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
    db_session: Session,
    document_ids: list[str],
) -> list[DbDocument]:
    stmt = select(DbDocument).where(DbDocument.id.in_(document_ids))
    documents = db_session.execute(stmt).scalars().all()
    return list(documents)


def get_document_connector_count(
    db_session: Session,
    document_id: str,
) -> int:
    results = get_document_connector_counts(db_session, [document_id])
    if not results or len(results) == 0:
        return 0

    return results[0][1]


def get_document_connector_counts(
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


def get_document_counts_for_cc_pairs(
    db_session: Session, cc_pair_identifiers: list[ConnectorCredentialPairIdentifier]
) -> Sequence[tuple[int, int, int]]:
    """Returns a sequence of tuples of (connector_id, credential_id, document count)"""

    # Prepare a list of (connector_id, credential_id) tuples
    cc_ids = [(x.connector_id, x.credential_id) for x in cc_pair_identifiers]

    stmt = (
        select(
            DocumentByConnectorCredentialPair.connector_id,
            DocumentByConnectorCredentialPair.credential_id,
            func.count(),
        )
        .where(
            tuple_(
                DocumentByConnectorCredentialPair.connector_id,
                DocumentByConnectorCredentialPair.credential_id,
            ).in_(cc_ids)
        )
        .group_by(
            DocumentByConnectorCredentialPair.connector_id,
            DocumentByConnectorCredentialPair.credential_id,
        )
    )

    return db_session.execute(stmt).all()  # type: ignore


def get_access_info_for_document(
    db_session: Session,
    document_id: str,
) -> tuple[str, list[str | None], bool] | None:
    """Gets access info for a single document by calling the get_access_info_for_documents function
    and passing a list with a single document ID.
    Args:
        db_session (Session): The database session to use.
        document_id (str): The document ID to fetch access info for.
    Returns:
        Optional[Tuple[str, List[str | None], bool]]: A tuple containing the document ID, a list of user emails,
        and a boolean indicating if the document is globally public, or None if no results are found.
    """
    results = get_access_info_for_documents(db_session, [document_id])
    if not results:
        return None

    return results[0]


def get_access_info_for_documents(
    db_session: Session,
    document_ids: list[str],
) -> Sequence[tuple[str, list[str | None], bool]]:
    """Gets back all relevant access info for the given documents. This includes
    the user_ids for cc pairs that the document is associated with + whether any
    of the associated cc pairs are intending to make the document globally public.
    Returns the list where each element contains:
    - Document ID (which is also the ID of the DocumentByConnectorCredentialPair)
    - List of emails of Onyx users with direct access to the doc (includes a "None" element if
      the connector was set up by an admin when auth was off
    - bool for whether the document is public (the document later can also be marked public by
      automatic permission sync step)
    """
    stmt = select(
        DocumentByConnectorCredentialPair.id,
        func.array_agg(func.coalesce(User.email, null())).label("user_emails"),
        func.bool_or(ConnectorCredentialPair.access_type == AccessType.PUBLIC).label(
            "public_doc"
        ),
    ).where(DocumentByConnectorCredentialPair.id.in_(document_ids))

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
        .outerjoin(
            User,
            and_(
                Credential.user_id == User.id,
                ConnectorCredentialPair.access_type != AccessType.SYNC,
            ),
        )
        # don't include CC pairs that are being deleted
        # NOTE: CC pairs can never go from DELETING to any other state -> it's safe to ignore them
        .where(ConnectorCredentialPair.status != ConnectorCredentialPairStatus.DELETING)
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
                    last_modified=datetime.now(timezone.utc),
                    primary_owners=doc.primary_owners,
                    secondary_owners=doc.secondary_owners,
                )
            )
            for doc in seen_documents.values()
        ]
    )

    # This does not update the permissions of the document if
    # the document already exists.
    on_conflict_stmt = insert_stmt.on_conflict_do_update(
        index_elements=["id"],  # Conflict target
        set_={
            "from_ingestion_api": insert_stmt.excluded.from_ingestion_api,
            "boost": insert_stmt.excluded.boost,
            "hidden": insert_stmt.excluded.hidden,
            "semantic_id": insert_stmt.excluded.semantic_id,
            "link": insert_stmt.excluded.link,
            "primary_owners": insert_stmt.excluded.primary_owners,
            "secondary_owners": insert_stmt.excluded.secondary_owners,
        },
    )
    db_session.execute(on_conflict_stmt)
    db_session.commit()


def upsert_document_by_connector_credential_pair(
    db_session: Session, connector_id: int, credential_id: int, document_ids: list[str]
) -> None:
    """NOTE: this function is Postgres specific. Not all DBs support the ON CONFLICT clause."""
    if not document_ids:
        logger.info("`document_ids` is empty. Skipping.")
        return

    insert_stmt = insert(DocumentByConnectorCredentialPair).values(
        [
            model_to_dict(
                DocumentByConnectorCredentialPair(
                    id=doc_id,
                    connector_id=connector_id,
                    credential_id=credential_id,
                )
            )
            for doc_id in document_ids
        ]
    )
    # for now, there are no columns to update. If more metadata is added, then this
    # needs to change to an `on_conflict_do_update`
    on_conflict_stmt = insert_stmt.on_conflict_do_nothing()
    db_session.execute(on_conflict_stmt)
    db_session.commit()


def update_docs_updated_at__no_commit(
    ids_to_new_updated_at: dict[str, datetime],
    db_session: Session,
) -> None:
    doc_ids = list(ids_to_new_updated_at.keys())
    documents_to_update = (
        db_session.query(DbDocument).filter(DbDocument.id.in_(doc_ids)).all()
    )

    for document in documents_to_update:
        document.doc_updated_at = ids_to_new_updated_at[document.id]


def update_docs_last_modified__no_commit(
    document_ids: list[str],
    db_session: Session,
) -> None:
    documents_to_update = (
        db_session.query(DbDocument).filter(DbDocument.id.in_(document_ids)).all()
    )

    now = datetime.now(timezone.utc)
    for doc in documents_to_update:
        doc.last_modified = now


def update_docs_chunk_count__no_commit(
    document_ids: list[str],
    doc_id_to_chunk_count: dict[str, int],
    db_session: Session,
) -> None:
    documents_to_update = (
        db_session.query(DbDocument).filter(DbDocument.id.in_(document_ids)).all()
    )
    for doc in documents_to_update:
        doc.chunk_count = doc_id_to_chunk_count[doc.id]


def mark_document_as_modified(
    document_id: str,
    db_session: Session,
) -> None:
    stmt = select(DbDocument).where(DbDocument.id == document_id)
    doc = db_session.scalar(stmt)
    if doc is None:
        raise ValueError(f"No document with ID: {document_id}")

    # update last_synced
    doc.last_modified = datetime.now(timezone.utc)
    db_session.commit()


def mark_document_as_synced(document_id: str, db_session: Session) -> None:
    stmt = select(DbDocument).where(DbDocument.id == document_id)
    doc = db_session.scalar(stmt)
    if doc is None:
        raise ValueError(f"No document with ID: {document_id}")

    # update last_synced
    doc.last_synced = datetime.now(timezone.utc)
    db_session.commit()


def delete_document_by_connector_credential_pair__no_commit(
    db_session: Session,
    document_id: str,
    connector_credential_pair_identifier: ConnectorCredentialPairIdentifier
    | None = None,
) -> None:
    """Deletes a single document by cc pair relationship entry.
    Foreign key rows are left in place.
    The implicit assumption is that the document itself still has other cc_pair
    references and needs to continue existing.
    """
    delete_documents_by_connector_credential_pair__no_commit(
        db_session=db_session,
        document_ids=[document_id],
        connector_credential_pair_identifier=connector_credential_pair_identifier,
    )


def delete_documents_by_connector_credential_pair__no_commit(
    db_session: Session,
    document_ids: list[str],
    connector_credential_pair_identifier: ConnectorCredentialPairIdentifier
    | None = None,
) -> None:
    """This deletes just the document by cc pair entries for a particular cc pair.
    Foreign key rows are left in place.
    The implicit assumption is that the document itself still has other cc_pair
    references and needs to continue existing.
    """
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
    """This completely deletes the documents from the db, including all foreign key relationships"""
    delete_documents_by_connector_credential_pair__no_commit(db_session, document_ids)
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
_LOCK_RETRY_DELAY = 10


@contextlib.contextmanager
def prepare_to_modify_documents(
    db_session: Session, document_ids: list[str], retry_delay: int = _LOCK_RETRY_DELAY
) -> Generator[TransactionalContext, None, None]:
    """Try and acquire locks for the documents to prevent other jobs from
    modifying them at the same time (e.g. avoid race conditions). This should be
    called ahead of any modification to Vespa. Locks should be released by the
    caller as soon as updates are complete by finishing the transaction.

    NOTE: only one commit is allowed within the context manager returned by this function.
    Multiple commits will result in a sqlalchemy.exc.InvalidRequestError.
    NOTE: this function will commit any existing transaction.
    """

    db_session.commit()  # ensure that we're not in a transaction

    lock_acquired = False
    for i in range(_NUM_LOCK_ATTEMPTS):
        try:
            with db_session.begin() as transaction:
                lock_acquired = acquire_document_locks(
                    db_session=db_session, document_ids=document_ids
                )
                if lock_acquired:
                    yield transaction
                    break
        except OperationalError as e:
            logger.warning(
                f"Failed to acquire locks for documents on attempt {i}, retrying. Error: {e}"
            )

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


def get_document(
    document_id: str,
    db_session: Session,
) -> DbDocument | None:
    stmt = select(DbDocument).where(DbDocument.id == document_id)
    doc: DbDocument | None = db_session.execute(stmt).scalar_one_or_none()
    return doc


def get_cc_pairs_for_document(
    db_session: Session,
    document_id: str,
) -> list[ConnectorCredentialPair]:
    stmt = (
        select(ConnectorCredentialPair)
        .join(
            DocumentByConnectorCredentialPair,
            and_(
                DocumentByConnectorCredentialPair.connector_id
                == ConnectorCredentialPair.connector_id,
                DocumentByConnectorCredentialPair.credential_id
                == ConnectorCredentialPair.credential_id,
            ),
        )
        .where(DocumentByConnectorCredentialPair.id == document_id)
    )
    return list(db_session.execute(stmt).scalars().all())


def get_document_sources(
    db_session: Session,
    document_ids: list[str],
) -> dict[str, DocumentSource]:
    """Gets the sources for a list of document IDs.
    Returns a dictionary mapping document ID to its source.
    If a document has multiple sources (multiple CC pairs), returns the first one found.
    """
    stmt = (
        select(
            DocumentByConnectorCredentialPair.id,
            Connector.source,
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
        .join(
            Connector,
            ConnectorCredentialPair.connector_id == Connector.id,
        )
        .where(DocumentByConnectorCredentialPair.id.in_(document_ids))
        .distinct()
    )

    results = db_session.execute(stmt).all()
    return {doc_id: source for doc_id, source in results}


def fetch_chunk_counts_for_documents(
    document_ids: list[str],
    db_session: Session,
) -> list[tuple[str, int]]:
    """
    Return a list of (document_id, chunk_count) tuples.
    If a document_id is not found in the database, it will be returned with a chunk_count of 0.
    """
    stmt = select(DbDocument.id, DbDocument.chunk_count).where(
        DbDocument.id.in_(document_ids)
    )

    results = db_session.execute(stmt).all()

    # Create a dictionary of document_id to chunk_count
    chunk_counts = {str(row.id): row.chunk_count or 0 for row in results}

    # Return a list of tuples, using 0 for documents not found in the database
    return [(doc_id, chunk_counts.get(doc_id, 0)) for doc_id in document_ids]


def fetch_chunk_count_for_document(
    document_id: str,
    db_session: Session,
) -> int | None:
    stmt = select(DbDocument.chunk_count).where(DbDocument.id == document_id)
    return db_session.execute(stmt).scalar_one_or_none()
