from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.db.document_set import check_if_cc_pairs_are_owned_by_groups
from onyx.db.models import (
    ConnectorCredentialPair,
    DocumentSet,
    DocumentSet__ConnectorCredentialPair,
    DocumentSet__User,
    DocumentSet__UserGroup,
    User__UserGroup,
    UserGroup,
)


def make_doc_set_private(
    document_set_id: int,
    user_ids: list[UUID] | None,
    group_ids: list[int] | None,
    db_session: Session,
) -> None:
    db_session.query(DocumentSet__User).filter(
        DocumentSet__User.document_set_id == document_set_id
    ).delete(synchronize_session="fetch")
    db_session.query(DocumentSet__UserGroup).filter(
        DocumentSet__UserGroup.document_set_id == document_set_id
    ).delete(synchronize_session="fetch")

    if user_ids:
        for user_uuid in user_ids:
            db_session.add(
                DocumentSet__User(document_set_id=document_set_id, user_id=user_uuid)
            )

    if group_ids:
        for group_id in group_ids:
            db_session.add(
                DocumentSet__UserGroup(
                    document_set_id=document_set_id, user_group_id=group_id
                )
            )


def set_document_set_group_membership__no_commit(
    db_session: Session,
    user_group_id: int,
    to_attach: Sequence[DocumentSet],
    to_detach: Sequence[DocumentSet],
) -> bool:
    """Attach/detach ``user_group_id`` on each document set, leaving the rest of each set
    untouched. Returns whether anything changed — callers commit and kick the index sync
    off that. Re-applies update_document_set's constraint that a private set's connectors
    must be reachable from every group it's shared with."""
    existing = {
        row.document_set_id: row
        for row in db_session.scalars(
            select(DocumentSet__UserGroup).where(
                DocumentSet__UserGroup.document_set_id.in_(
                    [document_set.id for document_set in (*to_attach, *to_detach)]
                ),
                DocumentSet__UserGroup.user_group_id == user_group_id,
            )
        )
    }
    # Drop the no-ops before the sync guard so a redundant save doesn't fail on a set
    # that happens to be syncing.
    attaching = [
        document_set for document_set in to_attach if document_set.id not in existing
    ]
    detaching = [
        document_set for document_set in to_detach if document_set.id in existing
    ]
    if not attaching and not detaching:
        return False

    syncing = next(
        (
            document_set
            for document_set in (*attaching, *detaching)
            if not document_set.is_up_to_date
        ),
        None,
    )
    if syncing is not None:
        raise ValueError(
            f"Document set '{syncing.name}' is still syncing. "
            "Please wait for it to finish, and then try again."
        )

    # One check for the batch — the requested group is the same for every set.
    private_ids = [
        document_set.id for document_set in attaching if not document_set.is_public
    ]
    if private_ids:
        cc_pair_ids = list(
            db_session.scalars(
                select(
                    DocumentSet__ConnectorCredentialPair.connector_credential_pair_id
                ).where(
                    DocumentSet__ConnectorCredentialPair.document_set_id.in_(
                        private_ids
                    ),
                    DocumentSet__ConnectorCredentialPair.is_current.is_(True),
                )
            )
        )
        check_if_cc_pairs_are_owned_by_groups(
            db_session=db_session,
            cc_pair_ids=cc_pair_ids,
            group_ids=[user_group_id],
        )

    for document_set in attaching:
        db_session.add(
            DocumentSet__UserGroup(
                document_set_id=document_set.id, user_group_id=user_group_id
            )
        )
    for document_set in detaching:
        db_session.delete(existing[document_set.id])

    for document_set in (*attaching, *detaching):
        if not DISABLE_VECTOR_DB:
            document_set.is_up_to_date = False
        document_set.time_last_modified_by_user = func.now()
    return True


def delete_document_set_privacy__no_commit(
    document_set_id: int, db_session: Session
) -> None:
    db_session.query(DocumentSet__User).filter(
        DocumentSet__User.document_set_id == document_set_id
    ).delete(synchronize_session="fetch")

    db_session.query(DocumentSet__UserGroup).filter(
        DocumentSet__UserGroup.document_set_id == document_set_id
    ).delete(synchronize_session="fetch")


def fetch_document_sets(
    user_id: UUID | None,
    db_session: Session,
    include_outdated: bool = True,  # Parameter only for versioned implementation, unused  # noqa: ARG001
) -> list[tuple[DocumentSet, list[ConnectorCredentialPair]]]:
    assert user_id is not None

    # Public document sets
    public_document_sets = (
        db_session.query(DocumentSet)
        .filter(DocumentSet.is_public == True)  # noqa
        .all()
    )

    # Document sets via shared user relationships
    shared_document_sets = (
        db_session.query(DocumentSet)
        .join(DocumentSet__User, DocumentSet.id == DocumentSet__User.document_set_id)
        .filter(DocumentSet__User.user_id == user_id)
        .all()
    )

    # Document sets via groups
    # First, find the user groups the user belongs to
    user_groups = (
        db_session.query(UserGroup)
        .join(User__UserGroup, UserGroup.id == User__UserGroup.user_group_id)
        .filter(User__UserGroup.user_id == user_id)
        .all()
    )

    group_document_sets = []
    for group in user_groups:
        group_document_sets.extend(
            db_session.query(DocumentSet)
            .join(
                DocumentSet__UserGroup,
                DocumentSet.id == DocumentSet__UserGroup.document_set_id,
            )
            .filter(DocumentSet__UserGroup.user_group_id == group.id)
            .all()
        )

    # Combine and deduplicate document sets from all sources
    all_document_sets = list(
        set(public_document_sets + shared_document_sets + group_document_sets)
    )

    document_set_with_cc_pairs: list[
        tuple[DocumentSet, list[ConnectorCredentialPair]]
    ] = []

    for document_set in all_document_sets:
        # Fetch the associated ConnectorCredentialPairs
        cc_pairs = (
            db_session.query(ConnectorCredentialPair)
            .join(
                DocumentSet__ConnectorCredentialPair,
                ConnectorCredentialPair.id
                == DocumentSet__ConnectorCredentialPair.connector_credential_pair_id,
            )
            .filter(
                DocumentSet__ConnectorCredentialPair.document_set_id == document_set.id,
            )
            .all()
        )

        document_set_with_cc_pairs.append((document_set, cc_pairs))

    return document_set_with_cc_pairs
