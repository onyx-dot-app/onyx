from collections.abc import Sequence
from operator import and_
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import Select
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.orm import Session

from ee.onyx.server.user_group.models import SetCuratorRequest
from ee.onyx.server.user_group.models import UserGroupCreate
from ee.onyx.server.user_group.models import UserGroupUpdate
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Credential__UserGroup
from onyx.db.models import Document
from onyx.db.models import DocumentByConnectorCredentialPair
from onyx.db.models import DocumentSet__UserGroup
from onyx.db.models import LLMProvider__UserGroup
from onyx.db.models import Persona__UserGroup
from onyx.db.models import TokenRateLimit__UserGroup
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.db.models import UserGroup
from onyx.db.models import UserGroup__ConnectorCredentialPair
from onyx.db.models import UserRole
from onyx.db.users import fetch_user_by_id
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _cleanup_user__user_group_relationships__no_commit(
    db_session: Session,
    user_group_id: int,
    user_ids: list[UUID] | None = None,
) -> None:
    """NOTE: does not commit the transaction."""
    where_clause = User__UserGroup.user_group_id == user_group_id
    if user_ids:
        where_clause &= User__UserGroup.user_id.in_(user_ids)

    user__user_group_relationships = db_session.scalars(
        select(User__UserGroup).where(where_clause)
    ).all()
    for user__user_group_relationship in user__user_group_relationships:
        db_session.delete(user__user_group_relationship)


def _cleanup_credential__user_group_relationships__no_commit(
    db_session: Session,
    user_group_id: int,
) -> None:
    """NOTE: does not commit the transaction."""
    db_session.query(Credential__UserGroup).filter(
        Credential__UserGroup.user_group_id == user_group_id
    ).delete(synchronize_session=False)


def _cleanup_llm_provider__user_group_relationships__no_commit(
    db_session: Session, user_group_id: int
) -> None:
    """NOTE: does not commit the transaction."""
    db_session.query(LLMProvider__UserGroup).filter(
        LLMProvider__UserGroup.user_group_id == user_group_id
    ).delete(synchronize_session=False)


def _cleanup_persona__user_group_relationships__no_commit(
    db_session: Session, user_group_id: int
) -> None:
    """NOTE: does not commit the transaction."""
    db_session.query(Persona__UserGroup).filter(
        Persona__UserGroup.user_group_id == user_group_id
    ).delete(synchronize_session=False)


def _cleanup_token_rate_limit__user_group_relationships__no_commit(
    db_session: Session, user_group_id: int
) -> None:
    """NOTE: does not commit the transaction."""
    token_rate_limit__user_group_relationships = db_session.scalars(
        select(TokenRateLimit__UserGroup).where(
            TokenRateLimit__UserGroup.user_group_id == user_group_id
        )
    ).all()
    for (
        token_rate_limit__user_group_relationship
    ) in token_rate_limit__user_group_relationships:
        db_session.delete(token_rate_limit__user_group_relationship)


def _cleanup_user_group__cc_pair_relationships__no_commit(
    db_session: Session, user_group_id: int, outdated_only: bool
) -> None:
    """NOTE: does not commit the transaction."""
    stmt = select(UserGroup__ConnectorCredentialPair).where(
        UserGroup__ConnectorCredentialPair.user_group_id == user_group_id
    )
    if outdated_only:
        stmt = stmt.where(
            UserGroup__ConnectorCredentialPair.is_current == False  # noqa: E712
        )
    user_group__cc_pair_relationships = db_session.scalars(stmt)
    for user_group__cc_pair_relationship in user_group__cc_pair_relationships:
        db_session.delete(user_group__cc_pair_relationship)


def _cleanup_document_set__user_group_relationships__no_commit(
    db_session: Session, user_group_id: int
) -> None:
    """NOTE: does not commit the transaction."""
    db_session.execute(
        delete(DocumentSet__UserGroup).where(
            DocumentSet__UserGroup.user_group_id == user_group_id
        )
    )


def validate_object_creation_for_user(
    db_session: Session,
    user: User | None,
    target_group_ids: list[int] | None = None,
    object_is_public: bool | None = None,
    object_is_perm_sync: bool | None = None,
    object_is_owned_by_user: bool = False,
    object_is_new: bool = False,
) -> None:
    """
    All users can create/edit permission synced objects if they don't specify a group
    All admin actions are allowed.
    Curators and global curators can create public objects.
    Prevents other non-admins from creating/editing:
    - public objects
    - objects with no groups
    - objects that belong to a group they don't curate
    """
    if object_is_perm_sync and not target_group_ids:
        return

    if not user or user.role == UserRole.ADMIN:
        return

    # Allow curators and global curators to create public objects
    # w/o associated groups IF the object is new/owned by them
    if (
        object_is_public
        and user.role in [UserRole.CURATOR, UserRole.GLOBAL_CURATOR]
        and (object_is_new or object_is_owned_by_user)
    ):
        return

    if object_is_public and user.role == UserRole.BASIC:
        detail = "User does not have permission to create public objects"
        logger.error(detail)
        raise HTTPException(
            status_code=400,
            detail=detail,
        )

    if not target_group_ids:
        detail = "Curators must specify 1+ groups"
        logger.error(detail)
        raise HTTPException(
            status_code=400,
            detail=detail,
        )

    user_curated_groups = fetch_user_groups_for_user(
        db_session=db_session,
        user_id=user.id,
        # Global curators can curate all groups they are member of
        only_curator_groups=user.role != UserRole.GLOBAL_CURATOR,
    )
    user_curated_group_ids = set([group.id for group in user_curated_groups])
    target_group_ids_set = set(target_group_ids)
    if not target_group_ids_set.issubset(user_curated_group_ids):
        detail = "Curators cannot control groups they don't curate"
        logger.error(detail)
        raise HTTPException(
            status_code=400,
            detail=detail,
        )


def fetch_user_group(db_session: Session, user_group_id: int) -> UserGroup | None:
    stmt = select(UserGroup).where(UserGroup.id == user_group_id)
    return db_session.scalar(stmt)


def fetch_user_groups(
    db_session: Session, only_up_to_date: bool = True
) -> Sequence[UserGroup]:
    """
    Fetches user groups from the database.

    This function retrieves a sequence of `UserGroup` objects from the database.
    If `only_up_to_date` is set to `True`, it filters the user groups to return only those
    that are marked as up-to-date (`is_up_to_date` is `True`).

    Args:
        db_session (Session): The SQLAlchemy session used to query the database.
        only_up_to_date (bool, optional): Flag to determine whether to filter the results
            to include only up to date user groups. Defaults to `True`.

    Returns:
        Sequence[UserGroup]: A sequence of `UserGroup` objects matching the query criteria.
    """
    stmt = select(UserGroup)
    if only_up_to_date:
        stmt = stmt.where(UserGroup.is_up_to_date == True)  # noqa: E712
    return db_session.scalars(stmt).all()


def fetch_user_groups_for_user(
    db_session: Session, user_id: UUID, only_curator_groups: bool = False
) -> Sequence[UserGroup]:
    stmt = (
        select(UserGroup)
        .join(User__UserGroup, User__UserGroup.user_group_id == UserGroup.id)
        .join(User, User.id == User__UserGroup.user_id)  # type: ignore
        .where(User.id == user_id)  # type: ignore
    )
    if only_curator_groups:
        stmt = stmt.where(User__UserGroup.is_curator == True)  # noqa: E712
    return db_session.scalars(stmt).all()


def construct_document_id_select_by_usergroup(
    user_group_id: int,
) -> Select:
    """This returns a statement that should be executed using
    .yield_per() to minimize overhead. The primary consumers of this function
    are background processing task generators."""
    stmt = (
        select(Document.id)
        .join(
            DocumentByConnectorCredentialPair,
            Document.id == DocumentByConnectorCredentialPair.id,
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
            UserGroup__ConnectorCredentialPair,
            UserGroup__ConnectorCredentialPair.cc_pair_id == ConnectorCredentialPair.id,
        )
        .join(
            UserGroup,
            UserGroup__ConnectorCredentialPair.user_group_id == UserGroup.id,
        )
        .where(UserGroup.id == user_group_id)
        .order_by(Document.id)
    )
    stmt = stmt.distinct()
    return stmt


def fetch_documents_for_user_group_paginated(
    db_session: Session,
    user_group_id: int,
    last_document_id: str | None = None,
    limit: int = 100,
) -> tuple[Sequence[Document], str | None]:
    stmt = (
        select(Document)
        .join(
            DocumentByConnectorCredentialPair,
            Document.id == DocumentByConnectorCredentialPair.id,
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
            UserGroup__ConnectorCredentialPair,
            UserGroup__ConnectorCredentialPair.cc_pair_id == ConnectorCredentialPair.id,
        )
        .join(
            UserGroup,
            UserGroup__ConnectorCredentialPair.user_group_id == UserGroup.id,
        )
        .where(UserGroup.id == user_group_id)
        .order_by(Document.id)
        .limit(limit)
    )
    if last_document_id is not None:
        stmt = stmt.where(Document.id > last_document_id)
    stmt = stmt.distinct()

    documents = db_session.scalars(stmt).all()
    return documents, documents[-1].id if documents else None


def fetch_user_groups_for_documents(
    db_session: Session,
    document_ids: list[str],
) -> Sequence[tuple[str, list[str]]]:
    """
    Fetches all user groups that have access to the given documents.

    NOTE: this doesn't include groups if the cc_pair is access type SYNC
    """
    stmt = (
        select(Document.id, func.array_agg(UserGroup.name))
        .join(
            UserGroup__ConnectorCredentialPair,
            UserGroup.id == UserGroup__ConnectorCredentialPair.user_group_id,
        )
        .join(
            ConnectorCredentialPair,
            and_(
                ConnectorCredentialPair.id
                == UserGroup__ConnectorCredentialPair.cc_pair_id,
                ConnectorCredentialPair.access_type != AccessType.SYNC,
            ),
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
        .join(Document, Document.id == DocumentByConnectorCredentialPair.id)
        .where(Document.id.in_(document_ids))
        .where(UserGroup__ConnectorCredentialPair.is_current == True)  # noqa: E712
        # don't include CC pairs that are being deleted
        # NOTE: CC pairs can never go from DELETING to any other state -> it's safe to ignore them
        .where(ConnectorCredentialPair.status != ConnectorCredentialPairStatus.DELETING)
        .group_by(Document.id)
    )

    return db_session.execute(stmt).all()  # type: ignore


def _check_user_group_is_modifiable(user_group: UserGroup) -> None:
    if not user_group.is_up_to_date:
        raise ValueError(
            "Specified user group is currently syncing. Wait until the current "
            "sync has finished before editing."
        )


def _add_user__user_group_relationships__no_commit(
    db_session: Session, user_group_id: int, user_ids: list[UUID]
) -> list[User__UserGroup]:
    """NOTE: does not commit the transaction."""
    relationships = [
        User__UserGroup(user_id=user_id, user_group_id=user_group_id)
        for user_id in user_ids
    ]
    db_session.add_all(relationships)
    return relationships


def _add_user_group__cc_pair_relationships__no_commit(
    db_session: Session, user_group_id: int, cc_pair_ids: list[int]
) -> list[UserGroup__ConnectorCredentialPair]:
    """NOTE: does not commit the transaction."""
    relationships = [
        UserGroup__ConnectorCredentialPair(
            user_group_id=user_group_id, cc_pair_id=cc_pair_id
        )
        for cc_pair_id in cc_pair_ids
    ]
    db_session.add_all(relationships)
    return relationships


def insert_user_group(db_session: Session, user_group: UserGroupCreate) -> UserGroup:
    db_user_group = UserGroup(
        name=user_group.name, time_last_modified_by_user=func.now()
    )
    db_session.add(db_user_group)
    db_session.flush()  # give the group an ID

    _add_user__user_group_relationships__no_commit(
        db_session=db_session,
        user_group_id=db_user_group.id,
        user_ids=user_group.user_ids,
    )
    _add_user_group__cc_pair_relationships__no_commit(
        db_session=db_session,
        user_group_id=db_user_group.id,
        cc_pair_ids=user_group.cc_pair_ids,
    )

    db_session.commit()
    return db_user_group


def _mark_user_group__cc_pair_relationships_outdated__no_commit(
    db_session: Session, user_group_id: int
) -> None:
    """NOTE: does not commit the transaction."""
    user_group__cc_pair_relationships = db_session.scalars(
        select(UserGroup__ConnectorCredentialPair).where(
            UserGroup__ConnectorCredentialPair.user_group_id == user_group_id
        )
    )
    for user_group__cc_pair_relationship in user_group__cc_pair_relationships:
        user_group__cc_pair_relationship.is_current = False


def _validate_curator_status__no_commit(
    db_session: Session,
    users: list[User],
) -> None:
    for user in users:
        # Check if the user is a curator in any of their groups
        curator_relationships = (
            db_session.query(User__UserGroup)
            .filter(
                User__UserGroup.user_id == user.id,
                User__UserGroup.is_curator == True,  # noqa: E712
            )
            .all()
        )

        # if the user is a curator in any of their groups, set their role to CURATOR
        # otherwise, set their role to BASIC only if they were previously a CURATOR
        if curator_relationships:
            user.role = UserRole.CURATOR
        elif user.role == UserRole.CURATOR:
            user.role = UserRole.BASIC
        db_session.add(user)


def remove_curator_status__no_commit(db_session: Session, user: User) -> None:
    stmt = (
        update(User__UserGroup)
        .where(User__UserGroup.user_id == user.id)
        .values(is_curator=False)
    )
    db_session.execute(stmt)
    _validate_curator_status__no_commit(db_session, [user])


def _validate_curator_relationship_update_requester(
    db_session: Session,
    user_group_id: int,
    user_making_change: User | None = None,
) -> None:
    """
    This function validates that the user making the change has the necessary permissions
    to update the curator relationship for the target user in the given user group.
    """

    if user_making_change is None or user_making_change.role == UserRole.ADMIN:
        return

    # check if the user making the change is a curator in the group they are changing the curator relationship for
    user_making_change_curator_groups = fetch_user_groups_for_user(
        db_session=db_session,
        user_id=user_making_change.id,
        # only check if the user making the change is a curator if they are a curator
        # otherwise, they are a global_curator and can update the curator relationship
        # for any group they are a member of
        only_curator_groups=user_making_change.role == UserRole.CURATOR,
    )
    requestor_curator_group_ids = [
        group.id for group in user_making_change_curator_groups
    ]
    if user_group_id not in requestor_curator_group_ids:
        raise ValueError(
            f"user making change {user_making_change.email} is not a curator,"
            f" admin, or global_curator for group '{user_group_id}'"
        )


def _validate_curator_relationship_update_request(
    db_session: Session,
    user_group_id: int,
    target_user: User,
) -> None:
    """
    This function validates that the curator_relationship_update request itself is valid.
    """
    if target_user.role == UserRole.ADMIN:
        raise ValueError(
            f"User '{target_user.email}' is an admin and therefore has all permissions "
            "of a curator. If you'd like this user to only have curator permissions, "
            "you must update their role to BASIC then assign them to be CURATOR in the "
            "appropriate groups."
        )
    elif target_user.role == UserRole.GLOBAL_CURATOR:
        raise ValueError(
            f"User '{target_user.email}' is a global_curator and therefore has all "
            "permissions of a curator for all groups. If you'd like this user to only "
            "have curator permissions for a specific group, you must update their role "
            "to BASIC then assign them to be CURATOR in the appropriate groups."
        )
    elif target_user.role not in [UserRole.CURATOR, UserRole.BASIC]:
        raise ValueError(
            f"This endpoint can only be used to update the curator relationship for "
            "users with the CURATOR or BASIC role. \n"
            f"Target user: {target_user.email} \n"
            f"Target user role: {target_user.role} \n"
        )

    # check if the target user is in the group they are changing the curator relationship for
    requested_user_groups = fetch_user_groups_for_user(
        db_session=db_session,
        user_id=target_user.id,
        only_curator_groups=False,
    )
    group_ids = [group.id for group in requested_user_groups]
    if user_group_id not in group_ids:
        raise ValueError(
            f"target user {target_user.email} is not in group '{user_group_id}'"
        )


def update_user_curator_relationship(
    db_session: Session,
    user_group_id: int,
    set_curator_request: SetCuratorRequest,
    user_making_change: User | None = None,
) -> None:
    target_user = fetch_user_by_id(db_session, set_curator_request.user_id)
    if not target_user:
        raise ValueError(f"User with id '{set_curator_request.user_id}' not found")

    _validate_curator_relationship_update_request(
        db_session=db_session,
        user_group_id=user_group_id,
        target_user=target_user,
    )

    _validate_curator_relationship_update_requester(
        db_session=db_session,
        user_group_id=user_group_id,
        user_making_change=user_making_change,
    )

    logger.info(
        f"user_making_change={user_making_change.email if user_making_change else 'None'} is "
        f"updating the curator relationship for user={target_user.email} "
        f"in group={user_group_id} to is_curator={set_curator_request.is_curator}"
    )

    relationship_to_update = (
        db_session.query(User__UserGroup)
        .filter(
            User__UserGroup.user_group_id == user_group_id,
            User__UserGroup.user_id == set_curator_request.user_id,
        )
        .first()
    )

    if relationship_to_update:
        relationship_to_update.is_curator = set_curator_request.is_curator
    else:
        relationship_to_update = User__UserGroup(
            user_group_id=user_group_id,
            user_id=set_curator_request.user_id,
            is_curator=True,
        )
        db_session.add(relationship_to_update)

    _validate_curator_status__no_commit(db_session, [target_user])
    db_session.commit()


def update_user_group(
    db_session: Session,
    user: User | None,
    user_group_id: int,
    user_group_update: UserGroupUpdate,
) -> UserGroup:
    """If successful, this can set db_user_group.is_up_to_date = False.
    That will be processed by check_for_vespa_user_groups_sync_task and trigger
    a long running background sync to Vespa.
    """
    stmt = select(UserGroup).where(UserGroup.id == user_group_id)
    db_user_group = db_session.scalar(stmt)
    if db_user_group is None:
        raise ValueError(f"UserGroup with id '{user_group_id}' not found")

    _check_user_group_is_modifiable(db_user_group)

    current_user_ids = set([user.id for user in db_user_group.users])
    updated_user_ids = set(user_group_update.user_ids)
    added_user_ids = list(updated_user_ids - current_user_ids)
    removed_user_ids = list(current_user_ids - updated_user_ids)

    # LEAVING THIS HERE FOR NOW FOR GIVING DIFFERENT ROLES
    # ACCESS TO DIFFERENT PERMISSIONS
    # if (removed_user_ids or added_user_ids) and (
    #     not user or user.role != UserRole.ADMIN
    # ):
    #     raise ValueError("Only admins can add or remove users from user groups")

    if removed_user_ids:
        _cleanup_user__user_group_relationships__no_commit(
            db_session=db_session,
            user_group_id=user_group_id,
            user_ids=removed_user_ids,
        )

    if added_user_ids:
        _add_user__user_group_relationships__no_commit(
            db_session=db_session,
            user_group_id=user_group_id,
            user_ids=added_user_ids,
        )

    cc_pairs_updated = set([cc_pair.id for cc_pair in db_user_group.cc_pairs]) != set(
        user_group_update.cc_pair_ids
    )
    if cc_pairs_updated:
        _mark_user_group__cc_pair_relationships_outdated__no_commit(
            db_session=db_session, user_group_id=user_group_id
        )
        _add_user_group__cc_pair_relationships__no_commit(
            db_session=db_session,
            user_group_id=db_user_group.id,
            cc_pair_ids=user_group_update.cc_pair_ids,
        )

    # only needs to sync with Vespa if the cc_pairs have been updated
    if cc_pairs_updated:
        db_user_group.is_up_to_date = False

    removed_users = db_session.scalars(
        select(User).where(User.id.in_(removed_user_ids))  # type: ignore
    ).unique()

    # Filter out admin and global curator users before validating curator status
    users_to_validate = [
        user
        for user in removed_users
        if user.role not in [UserRole.ADMIN, UserRole.GLOBAL_CURATOR]
    ]

    if users_to_validate:
        _validate_curator_status__no_commit(db_session, users_to_validate)

    # update "time_updated" to now
    db_user_group.time_last_modified_by_user = func.now()

    db_session.commit()
    return db_user_group


def prepare_user_group_for_deletion(db_session: Session, user_group_id: int) -> None:
    stmt = select(UserGroup).where(UserGroup.id == user_group_id)
    db_user_group = db_session.scalar(stmt)
    if db_user_group is None:
        raise ValueError(f"UserGroup with id '{user_group_id}' not found")

    _check_user_group_is_modifiable(db_user_group)

    _mark_user_group__cc_pair_relationships_outdated__no_commit(
        db_session=db_session, user_group_id=user_group_id
    )

    _cleanup_credential__user_group_relationships__no_commit(
        db_session=db_session, user_group_id=user_group_id
    )
    _cleanup_user__user_group_relationships__no_commit(
        db_session=db_session, user_group_id=user_group_id
    )
    _cleanup_token_rate_limit__user_group_relationships__no_commit(
        db_session=db_session, user_group_id=user_group_id
    )
    _cleanup_document_set__user_group_relationships__no_commit(
        db_session=db_session, user_group_id=user_group_id
    )
    _cleanup_persona__user_group_relationships__no_commit(
        db_session=db_session, user_group_id=user_group_id
    )
    _cleanup_user_group__cc_pair_relationships__no_commit(
        db_session=db_session,
        user_group_id=user_group_id,
        outdated_only=False,
    )
    _cleanup_llm_provider__user_group_relationships__no_commit(
        db_session=db_session, user_group_id=user_group_id
    )

    db_user_group.is_up_to_date = False
    db_user_group.is_up_for_deletion = True
    db_session.commit()


def delete_user_group(db_session: Session, user_group: UserGroup) -> None:
    """
    This assumes that all the fk cleanup has already been done.
    """
    db_session.delete(user_group)
    db_session.commit()


def mark_user_group_as_synced(db_session: Session, user_group: UserGroup) -> None:
    # cleanup outdated relationships
    _cleanup_user_group__cc_pair_relationships__no_commit(
        db_session=db_session, user_group_id=user_group.id, outdated_only=True
    )
    user_group.is_up_to_date = True
    db_session.commit()


def delete_user_group_cc_pair_relationship__no_commit(
    cc_pair_id: int, db_session: Session
) -> None:
    """Deletes all rows from UserGroup__ConnectorCredentialPair where the
    connector_credential_pair_id matches the given cc_pair_id.

    Should be used very carefully (only for connectors that are being deleted)."""
    cc_pair = get_connector_credential_pair_from_id(
        db_session=db_session,
        cc_pair_id=cc_pair_id,
    )
    if not cc_pair:
        raise ValueError(f"Connector Credential Pair '{cc_pair_id}' does not exist")

    if cc_pair.status != ConnectorCredentialPairStatus.DELETING:
        raise ValueError(
            f"Connector Credential Pair '{cc_pair_id}' is not in the DELETING state. status={cc_pair.status}"
        )

    delete_stmt = delete(UserGroup__ConnectorCredentialPair).where(
        UserGroup__ConnectorCredentialPair.cc_pair_id == cc_pair_id,
    )
    db_session.execute(delete_stmt)
