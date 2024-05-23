from collections.abc import Sequence
from typing import cast
from uuid import UUID

from sqlalchemy import and_
from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.orm import Session

from danswer.db.models import ConnectorCredentialPair
from danswer.db.models import Document
from danswer.db.models import DocumentByConnectorCredentialPair
from danswer.db.models import DocumentSet as DocumentSetDBModel
from danswer.db.models import DocumentSet__ConnectorCredentialPair
from danswer.server.features.document_set.models import DocumentSetCreationRequest
from danswer.server.features.document_set.models import DocumentSetUpdateRequest
from danswer.utils.variable_functionality import fetch_versioned_implementation


def _delete_document_set_cc_pairs__no_commit(
    db_session: Session, document_set_id: int, is_current: bool | None = None
) -> None:
    """NOTE: does not commit transaction, this must be done by the caller"""
    stmt = delete(DocumentSet__ConnectorCredentialPair).where(
        DocumentSet__ConnectorCredentialPair.document_set_id == document_set_id
    )
    if is_current is not None:
        stmt = stmt.where(DocumentSet__ConnectorCredentialPair.is_current == is_current)
    db_session.execute(stmt)


def _mark_document_set_cc_pairs_as_outdated__no_commit(
    db_session: Session, document_set_id: int
) -> None:
    """NOTE: does not commit transaction, this must be done by the caller"""
    stmt = select(DocumentSet__ConnectorCredentialPair).where(
        DocumentSet__ConnectorCredentialPair.document_set_id == document_set_id
    )
    for row in db_session.scalars(stmt):
        row.is_current = False


def delete_document_set_privacy__no_commit(
    document_set_id: int, db_session: Session
) -> None:
    """No private document sets in Danswer MIT"""


def get_document_set_by_id(
    db_session: Session, document_set_id: int
) -> DocumentSetDBModel | None:
    return db_session.scalar(
        select(DocumentSetDBModel).where(DocumentSetDBModel.id == document_set_id)
    )


def get_document_set_by_name(
    db_session: Session, document_set_name: str
) -> DocumentSetDBModel | None:
    return db_session.scalar(
        select(DocumentSetDBModel).where(DocumentSetDBModel.name == document_set_name)
    )


def get_document_sets_by_ids(
    db_session: Session, document_set_ids: list[int]
) -> Sequence[DocumentSetDBModel]:
    if not document_set_ids:
        return []
    return db_session.scalars(
        select(DocumentSetDBModel).where(DocumentSetDBModel.id.in_(document_set_ids))
    ).all()


def make_doc_set_private(
    document_set_id: int,
    user_ids: list[UUID] | None,
    group_ids: list[int] | None,
    db_session: Session,
) -> None:
    # May cause error if someone switches down to MIT from EE
    if user_ids or group_ids:
        raise NotImplementedError("Danswer MIT does not support private Document Sets")


def insert_document_set(
    document_set_creation_request: DocumentSetCreationRequest,
    user_id: UUID | None,
    db_session: Session,
) -> tuple[DocumentSetDBModel, list[DocumentSet__ConnectorCredentialPair]]:
    if not document_set_creation_request.cc_pair_ids:
        # It's cc-pairs in actuality but the UI displays this error
        raise ValueError("Cannot create a document set with no Connectors")

    # start a transaction
    db_session.begin()

    try:
        new_document_set_row = DocumentSetDBModel(
            name=document_set_creation_request.name,
            description=document_set_creation_request.description,
            user_id=user_id,
            is_public=document_set_creation_request.is_public,
        )
        db_session.add(new_document_set_row)
        db_session.flush()  # ensure the new document set gets assigned an ID

        ds_cc_pairs = [
            DocumentSet__ConnectorCredentialPair(
                document_set_id=new_document_set_row.id,
                connector_credential_pair_id=cc_pair_id,
                is_current=True,
            )
            for cc_pair_id in document_set_creation_request.cc_pair_ids
        ]
        db_session.add_all(ds_cc_pairs)

        versioned_private_doc_set_fn = fetch_versioned_implementation(
            "danswer.db.document_set", "make_doc_set_private"
        )

        # Private Document Sets
        versioned_private_doc_set_fn(
            document_set_id=new_document_set_row.id,
            user_ids=document_set_creation_request.users,
            group_ids=document_set_creation_request.groups,
            db_session=db_session,
        )

        db_session.commit()
    except:
        db_session.rollback()
        raise

    return new_document_set_row, ds_cc_pairs


def update_document_set(
    document_set_update_request: DocumentSetUpdateRequest, db_session: Session
) -> tuple[DocumentSetDBModel, list[DocumentSet__ConnectorCredentialPair]]:
    if not document_set_update_request.cc_pair_ids:
        # It's cc-pairs in actuality but the UI displays this error
        raise ValueError("Cannot create a document set with no Connectors")

    # start a transaction
    db_session.begin()

    try:
        # update the description
        document_set_row = get_document_set_by_id(
            db_session=db_session, document_set_id=document_set_update_request.id
        )
        if document_set_row is None:
            raise ValueError(
                f"No document set with ID '{document_set_update_request.id}'"
            )
        if not document_set_row.is_up_to_date:
            raise ValueError(
                "Cannot update document set while it is syncing. Please wait "
                "for it to finish syncing, and then try again."
            )

        document_set_row.description = document_set_update_request.description
        document_set_row.is_up_to_date = False
        document_set_row.is_public = document_set_update_request.is_public

        versioned_private_doc_set_fn = fetch_versioned_implementation(
            "danswer.db.document_set", "make_doc_set_private"
        )

        # Private Document Sets
        versioned_private_doc_set_fn(
            document_set_id=document_set_row.id,
            user_ids=document_set_update_request.users,
            group_ids=document_set_update_request.groups,
            db_session=db_session,
        )

        # update the attached CC pairs
        # first, mark all existing CC pairs as not current
        _mark_document_set_cc_pairs_as_outdated__no_commit(
            db_session=db_session, document_set_id=document_set_row.id
        )
        # add in rows for the new CC pairs
        ds_cc_pairs = [
            DocumentSet__ConnectorCredentialPair(
                document_set_id=document_set_update_request.id,
                connector_credential_pair_id=cc_pair_id,
                is_current=True,
            )
            for cc_pair_id in document_set_update_request.cc_pair_ids
        ]
        db_session.add_all(ds_cc_pairs)
        db_session.commit()
    except:
        db_session.rollback()
        raise

    return document_set_row, ds_cc_pairs


def mark_document_set_as_synced(document_set_id: int, db_session: Session) -> None:
    stmt = select(DocumentSetDBModel).where(DocumentSetDBModel.id == document_set_id)
    document_set = db_session.scalar(stmt)
    if document_set is None:
        raise ValueError(f"No document set with ID: {document_set_id}")

    # mark as up to date
    document_set.is_up_to_date = True
    # delete outdated relationship table rows
    _delete_document_set_cc_pairs__no_commit(
        db_session=db_session, document_set_id=document_set_id, is_current=False
    )
    db_session.commit()


def delete_document_set(
    document_set_row: DocumentSetDBModel, db_session: Session
) -> None:
    # delete all relationships to CC pairs
    _delete_document_set_cc_pairs__no_commit(
        db_session=db_session, document_set_id=document_set_row.id
    )
    db_session.delete(document_set_row)
    db_session.commit()


def mark_document_set_as_to_be_deleted(
    document_set_id: int, db_session: Session
) -> None:
    """Cleans up all document_set -> cc_pair relationships and marks the document set
    as needing an update. The actual document set row will be deleted by the background
    job which syncs these changes to Vespa."""
    # start a transaction
    db_session.begin()

    try:
        document_set_row = get_document_set_by_id(
            db_session=db_session, document_set_id=document_set_id
        )
        if document_set_row is None:
            raise ValueError(f"No document set with ID: '{document_set_id}'")
        if not document_set_row.is_up_to_date:
            raise ValueError(
                "Cannot delete document set while it is syncing. Please wait "
                "for it to finish syncing, and then try again."
            )

        # delete all relationships to CC pairs
        _delete_document_set_cc_pairs__no_commit(
            db_session=db_session, document_set_id=document_set_id
        )

        # delete all private document set information
        versioned_delete_private_fn = fetch_versioned_implementation(
            "danswer.db.document_set", "delete_document_set_privacy__no_commit"
        )
        versioned_delete_private_fn(
            document_set_id=document_set_id, db_session=db_session
        )

        # mark the row as needing a sync, it will be deleted there since there
        # are no more relationships to cc pairs
        document_set_row.is_up_to_date = False
        db_session.commit()
    except:
        db_session.rollback()
        raise


def mark_cc_pair__document_set_relationships_to_be_deleted__no_commit(
    cc_pair_id: int, db_session: Session
) -> set[int]:
    """Marks all CC Pair -> Document Set relationships for the specified
    `cc_pair_id` as not current and returns the list of all document set IDs
    affected.

    NOTE: rases a `ValueError` if any of the document sets are currently syncing
    to avoid getting into a bad state."""
    document_set__cc_pair_relationships = db_session.scalars(
        select(DocumentSet__ConnectorCredentialPair).where(
            DocumentSet__ConnectorCredentialPair.connector_credential_pair_id
            == cc_pair_id
        )
    ).all()

    document_set_ids_touched: set[int] = set()
    for document_set__cc_pair_relationship in document_set__cc_pair_relationships:
        document_set__cc_pair_relationship.is_current = False

        if not document_set__cc_pair_relationship.document_set.is_up_to_date:
            raise ValueError(
                "Cannot delete CC pair while it is attached to a document set "
                "that is syncing. Please wait for the document set to finish "
                "syncing, and then try again."
            )

        document_set__cc_pair_relationship.document_set.is_up_to_date = False
        document_set_ids_touched.add(document_set__cc_pair_relationship.document_set_id)

    return document_set_ids_touched


def fetch_document_sets(
    user_id: UUID | None, db_session: Session, include_outdated: bool = False
) -> list[tuple[DocumentSetDBModel, list[ConnectorCredentialPair]]]:
    """Return is a list where each element contains a tuple of:
    1. The document set itself
    2. All CC pairs associated with the document set"""
    stmt = (
        select(DocumentSetDBModel, ConnectorCredentialPair)
        .join(
            DocumentSet__ConnectorCredentialPair,
            DocumentSetDBModel.id
            == DocumentSet__ConnectorCredentialPair.document_set_id,
            isouter=True,  # outer join is needed to also fetch document sets with no cc pairs
        )
        .join(
            ConnectorCredentialPair,
            ConnectorCredentialPair.id
            == DocumentSet__ConnectorCredentialPair.connector_credential_pair_id,
            isouter=True,  # outer join is needed to also fetch document sets with no cc pairs
        )
    )
    if not include_outdated:
        stmt = stmt.where(
            or_(
                DocumentSet__ConnectorCredentialPair.is_current == True,  # noqa: E712
                # `None` handles case where no CC Pairs exist for a Document Set
                DocumentSet__ConnectorCredentialPair.is_current.is_(None),
            )
        )

    results = cast(
        list[tuple[DocumentSetDBModel, ConnectorCredentialPair | None]],
        db_session.execute(stmt).all(),
    )

    aggregated_results: dict[
        int, tuple[DocumentSetDBModel, list[ConnectorCredentialPair]]
    ] = {}
    for document_set, cc_pair in results:
        if document_set.id not in aggregated_results:
            aggregated_results[document_set.id] = (
                document_set,
                [cc_pair] if cc_pair else [],
            )
        else:
            if cc_pair:
                aggregated_results[document_set.id][1].append(cc_pair)

    return [
        (document_set, cc_pairs)
        for document_set, cc_pairs in aggregated_results.values()
    ]


def fetch_all_document_sets(db_session: Session) -> Sequence[DocumentSetDBModel]:
    """Used for Admin UI where they should have visibility into all document sets"""
    return db_session.scalars(select(DocumentSetDBModel)).all()


def fetch_user_document_sets(
    user_id: UUID | None, db_session: Session
) -> list[tuple[DocumentSetDBModel, list[ConnectorCredentialPair]]]:
    # If Auth is turned off, all document sets become visible
    # document sets are not permission enforced, only for organizational purposes
    # the documents themselves are permission enforced
    if user_id is None:
        return fetch_document_sets(
            user_id=user_id, db_session=db_session, include_outdated=True
        )

    versioned_fetch_doc_sets_fn = fetch_versioned_implementation(
        "danswer.db.document_set", "fetch_document_sets"
    )

    return versioned_fetch_doc_sets_fn(
        user_id=user_id, db_session=db_session, include_outdated=True
    )


def fetch_documents_for_document_set_paginated(
    document_set_id: int,
    db_session: Session,
    current_only: bool = True,
    last_document_id: str | None = None,
    limit: int = 100,
) -> tuple[Sequence[Document], str | None]:
    stmt = (
        select(Document)
        .join(
            DocumentByConnectorCredentialPair,
            DocumentByConnectorCredentialPair.id == Document.id,
        )
        .join(
            ConnectorCredentialPair,
            and_(
                ConnectorCredentialPair.connector_id
                == DocumentByConnectorCredentialPair.connector_id,
                ConnectorCredentialPair.credential_id
                == DocumentByConnectorCredentialPair.credential_id,
            ),
        )
        .join(
            DocumentSet__ConnectorCredentialPair,
            DocumentSet__ConnectorCredentialPair.connector_credential_pair_id
            == ConnectorCredentialPair.id,
        )
        .join(
            DocumentSetDBModel,
            DocumentSetDBModel.id
            == DocumentSet__ConnectorCredentialPair.document_set_id,
        )
        .where(DocumentSetDBModel.id == document_set_id)
        .order_by(Document.id)
        .limit(limit)
    )
    if last_document_id is not None:
        stmt = stmt.where(Document.id > last_document_id)
    if current_only:
        stmt = stmt.where(
            DocumentSet__ConnectorCredentialPair.is_current == True  # noqa: E712
        )
    stmt = stmt.distinct()

    documents = db_session.scalars(stmt).all()
    return documents, documents[-1].id if documents else None


def fetch_document_sets_for_documents(
    document_ids: list[str], db_session: Session
) -> Sequence[tuple[str, list[str]]]:
    stmt = (
        select(Document.id, func.array_agg(DocumentSetDBModel.name))
        .join(
            DocumentSet__ConnectorCredentialPair,
            DocumentSetDBModel.id
            == DocumentSet__ConnectorCredentialPair.document_set_id,
        )
        .join(
            ConnectorCredentialPair,
            ConnectorCredentialPair.id
            == DocumentSet__ConnectorCredentialPair.connector_credential_pair_id,
        )
        .join(
            DocumentByConnectorCredentialPair,
            and_(
                DocumentByConnectorCredentialPair.connector_id
                == ConnectorCredentialPair.connector_id,
                DocumentByConnectorCredentialPair.credential_id
                == ConnectorCredentialPair.credential_id,
            ),
        )
        .join(
            Document,
            Document.id == DocumentByConnectorCredentialPair.id,
        )
        .where(Document.id.in_(document_ids))
        .where(DocumentSet__ConnectorCredentialPair.is_current == True)  # noqa: E712
        .group_by(Document.id)
    )
    return db_session.execute(stmt).all()  # type: ignore


def get_or_create_document_set_by_name(
    db_session: Session,
    document_set_name: str,
    document_set_description: str = "Default Persona created Document-Set, "
    "please update description",
) -> DocumentSetDBModel:
    """This is used by the default personas which need to attach to document sets
    on server startup"""
    doc_set = get_document_set_by_name(db_session, document_set_name)
    if doc_set is not None:
        return doc_set

    new_doc_set = DocumentSetDBModel(
        name=document_set_name,
        description=document_set_description,
        user_id=None,
        is_up_to_date=True,
    )

    db_session.add(new_doc_set)
    db_session.commit()

    return new_doc_set


def check_document_sets_are_public(
    db_session: Session,
    document_set_ids: list[int],
) -> bool:
    """Checks if any of the CC-Pairs are Non Public (meaning that some documents in this document
    set is not Public"""
    connector_credential_pair_ids = (
        db_session.query(
            DocumentSet__ConnectorCredentialPair.connector_credential_pair_id
        )
        .filter(
            DocumentSet__ConnectorCredentialPair.document_set_id.in_(document_set_ids)
        )
        .subquery()
    )

    not_public_exists = (
        db_session.query(ConnectorCredentialPair.id)
        .filter(
            ConnectorCredentialPair.id.in_(
                connector_credential_pair_ids  # type:ignore
            ),
            ConnectorCredentialPair.is_public.is_(False),
        )
        .limit(1)
        .first()
        is not None
    )

    return not not_public_exists
