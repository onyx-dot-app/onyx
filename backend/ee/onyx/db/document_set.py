from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import DocumentSet
from onyx.db.models import DocumentSet__ConnectorCredentialPair
from onyx.db.models import DocumentSet__User
from onyx.db.models import DocumentSet__UserGroup
from onyx.db.models import User__UserGroup
from onyx.db.models import UserGroup


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
    include_outdated: bool = True,  # Parameter only for versioned implementation, unused
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

        document_set_with_cc_pairs.append((document_set, cc_pairs))  # type: ignore

    return document_set_with_cc_pairs
