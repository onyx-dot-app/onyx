from collections.abc import Sequence
from typing import cast
from typing import Optional
from uuid import UUID

from sqlalchemy import and_
from sqlalchemy import delete
from sqlalchemy import exists
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import Select
from sqlalchemy import select
from sqlalchemy.orm import aliased
from sqlalchemy.orm import Session

from enmedd.auth.schemas import TeamspaceRole
from enmedd.db.connector_credential_pair import get_cc_pair_groups_for_ids
from enmedd.db.connector_credential_pair import get_connector_credential_pairs
from enmedd.db.enums import AccessType
from enmedd.db.enums import ConnectorCredentialPairStatus
from enmedd.db.models import ConnectorCredentialPair
from enmedd.db.models import Document
from enmedd.db.models import DocumentByConnectorCredentialPair
from enmedd.db.models import DocumentSet as DocumentSetDBModel
from enmedd.db.models import DocumentSet__ConnectorCredentialPair
from enmedd.db.models import DocumentSet__Teamspace
from enmedd.db.models import User
from enmedd.db.models import User__Teamspace
from enmedd.db.models import UserRole
from enmedd.server.features.document_set.models import DocumentSetCreationRequest
from enmedd.server.features.document_set.models import DocumentSetUpdateRequest
from enmedd.utils.logger import setup_logger
from enmedd.utils.variable_functionality import fetch_versioned_implementation

logger = setup_logger()


def _add_user_filters(
    stmt: Select, user: User | None, get_editable: bool = True
) -> Select:
    # If user is None, assume the user is an admin or auth is disabled
    if user is None or user.role == UserRole.ADMIN:
        return stmt

    DocumentSet__UG = aliased(DocumentSet__Teamspace)
    User_Teams = aliased(User__Teamspace)
    """
    Here we select cc_pairs by relation:
    User -> User__Teamspace -> DocumentSet__Teamspace -> DocumentSet
    """
    stmt = stmt.outerjoin(DocumentSet__UG).outerjoin(
        User__Teamspace,
        User__Teamspace.teamspace_id == DocumentSet__UG.teamspace_id,
    )
    """
    Filter DocumentSets by:
    - if the user is in the teamspace that owns the DocumentSet
    - if editing is being done, we also filter out DocumentSets that are owned by groups
    that the user isn't a part of
    - if we are not editing, we show all DocumentSets in the groups the user is a part of
    (as well as public DocumentSets)
    """
    where_clause = User__Teamspace.user_id == user.id
    if user.role == TeamspaceRole.CREATOR and get_editable:
        where_clause &= User__Teamspace.role == True  # noqa: E712
    if get_editable:
        teamspace = select(User_Teams.teamspace_id).where(User_Teams.user_id == user.id)
        if user.role == TeamspaceRole.CREATOR:
            teamspace = teamspace.where(User_Teams.role == True)  # noqa: E712
        where_clause &= (
            ~exists()
            .where(DocumentSet__UG.document_set_id == DocumentSetDBModel.id)
            .where(~DocumentSet__UG.teamspace_id.in_(teamspace))
            .correlate(DocumentSetDBModel)
        )
    else:
        where_clause |= DocumentSetDBModel.is_public == True  # noqa: E712

    return stmt.where(where_clause)


logger = setup_logger()


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
    """No private document sets in enMedD AI MIT"""


def get_document_set_by_id(
    db_session: Session,
    document_set_id: int,
    user: User | None = None,
    get_editable: bool = True,
) -> DocumentSetDBModel | None:
    stmt = select(DocumentSetDBModel).distinct()
    stmt = stmt.where(DocumentSetDBModel.id == document_set_id)
    stmt = _add_user_filters(stmt=stmt, user=user, get_editable=get_editable)
    return db_session.scalar(stmt)


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
        raise NotImplementedError(
            "enMedD AI MIT does not support private Document Sets"
        )


def _check_if_cc_pairs_are_owned_by_groups(
    db_session: Session,
    cc_pair_ids: list[int],
    group_ids: list[int],
) -> None:
    """
    This function checks if the CC pairs are owned by the specified groups or public.
    If not, it raises a ValueError.
    """
    group_cc_pair_relationships = get_cc_pair_groups_for_ids(
        db_session=db_session,
        cc_pair_ids=cc_pair_ids,
    )

    group_cc_pair_relationships_set = {
        (relationship.cc_pair_id, relationship.teamspace_id)
        for relationship in group_cc_pair_relationships
    }

    missing_cc_pair_ids = []
    for cc_pair_id in cc_pair_ids:
        for group_id in group_ids:
            if (cc_pair_id, group_id) not in group_cc_pair_relationships_set:
                missing_cc_pair_ids.append(cc_pair_id)
                break

    if missing_cc_pair_ids:
        cc_pairs = get_connector_credential_pairs(
            db_session=db_session,
            ids=missing_cc_pair_ids,
        )
        for cc_pair in cc_pairs:
            if cc_pair.access_type != AccessType.PUBLIC:
                raise ValueError(
                    f"Connector Credential Pair with ID: '{cc_pair.id}'"
                    " is not owned by the specified groups"
                )


def insert_document_set(
    document_set_creation_request: DocumentSetCreationRequest,
    user_id: UUID | None,
    db_session: Session,
) -> tuple[DocumentSetDBModel, list[DocumentSet__ConnectorCredentialPair]]:
    if not document_set_creation_request.cc_pair_ids:
        # It's cc-pairs in actuality but the UI displays this error
        raise ValueError("Cannot create a document set with no Connectors")

    if not document_set_creation_request.is_public:
        _check_if_cc_pairs_are_owned_by_groups(
            db_session=db_session,
            cc_pair_ids=document_set_creation_request.cc_pair_ids,
            group_ids=document_set_creation_request.groups or [],
        )

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
            "enmedd.db.document_set", "make_doc_set_private"
        )

        # Private Document Sets
        versioned_private_doc_set_fn(
            document_set_id=new_document_set_row.id,
            user_ids=document_set_creation_request.users,
            group_ids=document_set_creation_request.groups,
            db_session=db_session,
        )

        db_session.commit()
    except Exception as e:
        db_session.rollback()
        logger.error(f"Error creating document set: {e}")

    return new_document_set_row, ds_cc_pairs


def update_document_set(
    db_session: Session,
    document_set_update_request: DocumentSetUpdateRequest,
    user: User | None = None,
) -> tuple[DocumentSetDBModel, list[DocumentSet__ConnectorCredentialPair]]:
    """If successful, this sets document_set_row.is_up_to_date = False.
    That will be processed via Celery in check_for_vespa_sync_task
    and trigger a long running background sync to Vespa.
    """
    if not document_set_update_request.cc_pair_ids:
        # It's cc-pairs in actuality but the UI displays this error
        raise ValueError("Cannot create a document set with no Connectors")

    if not document_set_update_request.is_public:
        _check_if_cc_pairs_are_owned_by_groups(
            db_session=db_session,
            cc_pair_ids=document_set_update_request.cc_pair_ids,
            group_ids=document_set_update_request.groups,
        )

    try:
        # update the description
        document_set_row = get_document_set_by_id(
            db_session=db_session,
            document_set_id=document_set_update_request.id,
            user=user,
            get_editable=True,
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
            "enmedd.db.document_set", "make_doc_set_private"
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
    db_session: Session,
    document_set_id: int,
    user: User | None = None,
    teamspace_id: Optional[int] = None,
) -> None:
    """Cleans up all document_set -> cc_pair relationships and marks the document set
    as needing an update. The actual document set row will be deleted by the background
    job which syncs these changes to Vespa."""

    try:
        if teamspace_id:
            teamspace_link = (
                db_session.query(DocumentSet__Teamspace)
                .filter_by(document_set_id=document_set_id, teamspace_id=teamspace_id)
                .first()
            )

            if teamspace_link:
                db_session.delete(teamspace_link)
                db_session.commit()
            else:
                raise ValueError(
                    f"No relationship found for document set ID '{document_set_id}' "
                    f"and teamspace ID '{teamspace_id}'."
                )
            return

        document_set_row = get_document_set_by_id(
            db_session=db_session,
            document_set_id=document_set_id,
            user=user,
            get_editable=True,
        )
        if document_set_row is None:
            error_msg = f"Document set with ID: '{document_set_id}' does not exist "
            if user is not None:
                error_msg += f"or is not editable by user with email: '{user.email}'"
            raise ValueError(error_msg)
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
            "enmedd.db.document_set", "delete_document_set_privacy__no_commit"
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


def delete_document_set_cc_pair_relationship__no_commit(
    connector_id: int, credential_id: int, db_session: Session
) -> None:
    """Deletes all rows from DocumentSet__ConnectorCredentialPair where the
    connector_credential_pair_id matches the given cc_pair_id."""
    delete_stmt = delete(DocumentSet__ConnectorCredentialPair).where(
        and_(
            ConnectorCredentialPair.connector_id == connector_id,
            ConnectorCredentialPair.credential_id == credential_id,
            DocumentSet__ConnectorCredentialPair.connector_credential_pair_id
            == ConnectorCredentialPair.id,
        )
    )
    db_session.execute(delete_stmt)


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


def fetch_all_document_sets_for_user(
    db_session: Session,
    user: User | None = None,
    get_editable: bool = True,
) -> Sequence[DocumentSetDBModel]:
    stmt = select(DocumentSetDBModel).distinct()
    stmt = _add_user_filters(stmt, user, get_editable=get_editable)
    return db_session.scalars(stmt).all()


def fetch_all_document_sets(db_session: Session) -> Sequence[DocumentSetDBModel]:
    """Used for Admin UI where they should have visibility into all document sets"""
    return db_session.scalars(select(DocumentSetDBModel)).all()


def fetch_document_sets_by_teamspace(
    teamspace_id: int, db_session: Session
) -> Sequence[DocumentSetDBModel]:
    """Fetch document sets for a specific teamspace."""
    return (
        db_session.query(DocumentSetDBModel)
        .join(
            DocumentSet__Teamspace,
            DocumentSetDBModel.id == DocumentSet__Teamspace.document_set_id,
        )
        .filter(DocumentSet__Teamspace.teamspace_id == teamspace_id)
        .all()
    )


def fetch_document_sets_by_teamspace_non_admin(
    teamspace_id: int, db_session: Session
) -> list[tuple[DocumentSetDBModel, list[ConnectorCredentialPair]]]:
    """Fetch document sets and associated connector-credential pairs for a specific teamspace."""
    document_set_data = (
        db_session.query(DocumentSetDBModel, ConnectorCredentialPair)
        .join(
            DocumentSet__Teamspace,
            DocumentSetDBModel.id == DocumentSet__Teamspace.document_set_id,
        )
        .join(
            DocumentSet__ConnectorCredentialPair,
            DocumentSetDBModel.id
            == DocumentSet__ConnectorCredentialPair.document_set_id,
        )
        .join(
            ConnectorCredentialPair,
            DocumentSet__ConnectorCredentialPair.connector_credential_pair_id
            == ConnectorCredentialPair.id,
        )
        .filter(DocumentSet__Teamspace.teamspace_id == teamspace_id)
        .all()
    )

    document_sets = {}
    for document_set, cc_pair in document_set_data:
        if document_set not in document_sets:
            document_sets[document_set] = []
        document_sets[document_set].append(cc_pair)

    return [(doc_set, cc_pairs) for doc_set, cc_pairs in document_sets.items()]


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
        "enmedd.db.document_set", "fetch_document_sets"
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


def construct_document_select_by_docset(
    document_set_id: int,
    current_only: bool = True,
) -> Select:
    """This returns a statement that should be executed using
    .yield_per() to minimize overhead. The primary consumers of this function
    are background processing task generators."""

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
    )

    if current_only:
        stmt = stmt.where(
            DocumentSet__ConnectorCredentialPair.is_current == True  # noqa: E712
        )

    stmt = stmt.distinct()
    return stmt


def fetch_document_sets_for_document(
    document_id: str,
    db_session: Session,
) -> list[str]:
    """
    Fetches the document set names for a single document ID.

    :param document_id: The ID of the document to fetch sets for.
    :param db_session: The SQLAlchemy session to use for the query.
    :return: A list of document set names, or None if no result is found.
    """
    result = fetch_document_sets_for_documents([document_id], db_session)
    if not result:
        return []

    return result[0][1]


def fetch_document_sets_for_documents(
    document_ids: list[str],
    db_session: Session,
) -> Sequence[tuple[str, list[str]]]:
    """Gives back a list of (document_id, list[document_set_names]) tuples"""

    """Building subqueries"""
    # NOTE: have to build these subqueries first in order to guarantee that we get one
    # returned row for each specified document_id. Basically, we want to do the filters first,
    # then the outer joins.

    # don't include CC pairs that are being deleted
    # NOTE: CC pairs can never go from DELETING to any other state -> it's safe to ignore them
    # as we can assume their document sets are no longer relevant
    valid_cc_pairs_subquery = aliased(
        ConnectorCredentialPair,
        select(ConnectorCredentialPair)
        .where(
            ConnectorCredentialPair.status != ConnectorCredentialPairStatus.DELETING
        )  # noqa: E712
        .subquery(),
    )

    valid_document_set__cc_pairs_subquery = aliased(
        DocumentSet__ConnectorCredentialPair,
        select(DocumentSet__ConnectorCredentialPair)
        .where(DocumentSet__ConnectorCredentialPair.is_current == True)  # noqa: E712
        .subquery(),
    )
    """End building subqueries"""

    stmt = (
        select(
            Document.id,
            func.coalesce(
                func.array_remove(func.array_agg(DocumentSetDBModel.name), None), []
            ).label("document_set_names"),
        )
        # Here we select document sets by relation:
        # Document -> DocumentByConnectorCredentialPair -> ConnectorCredentialPair ->
        # DocumentSet__ConnectorCredentialPair -> DocumentSet
        .outerjoin(
            DocumentByConnectorCredentialPair,
            Document.id == DocumentByConnectorCredentialPair.id,
        )
        .outerjoin(
            valid_cc_pairs_subquery,
            and_(
                DocumentByConnectorCredentialPair.connector_id
                == valid_cc_pairs_subquery.connector_id,
                DocumentByConnectorCredentialPair.credential_id
                == valid_cc_pairs_subquery.credential_id,
            ),
        )
        .outerjoin(
            valid_document_set__cc_pairs_subquery,
            valid_cc_pairs_subquery.id
            == valid_document_set__cc_pairs_subquery.connector_credential_pair_id,
        )
        .outerjoin(
            DocumentSetDBModel,
            DocumentSetDBModel.id
            == valid_document_set__cc_pairs_subquery.document_set_id,
        )
        .where(Document.id.in_(document_ids))
        .group_by(Document.id)
    )
    return db_session.execute(stmt).all()  # type: ignore


def get_or_create_document_set_by_name(
    db_session: Session,
    document_set_name: str,
    document_set_description: str = "Default Assistant created Document-Set, "
    "please update description",
) -> DocumentSetDBModel:
    """This is used by the default assistants which need to attach to document sets
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
            ConnectorCredentialPair.access_type != AccessType.PUBLIC,
        )
        .limit(1)
        .first()
        is not None
    )

    return not not_public_exists