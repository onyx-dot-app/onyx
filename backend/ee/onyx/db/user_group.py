from collections import defaultdict
from collections.abc import Sequence
from operator import and_
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import Select
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from ee.onyx.server.user_group.models import UserGroupCreate
from ee.onyx.server.user_group.models import UserGroupUpdate
from onyx.auth.permissions import has_permission
from onyx.auth.scoped_permissions import assert_manages_group
from onyx.auth.scoped_permissions import assert_within_scope
from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.db.connector_credential_pair import get_cc_pair_groups_for_ids
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import GrantSource
from onyx.db.enums import Permission
from onyx.db.enums import PermissionAuthority
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Credential
from onyx.db.models import Credential__UserGroup
from onyx.db.models import Document
from onyx.db.models import DocumentByConnectorCredentialPair
from onyx.db.models import DocumentSet
from onyx.db.models import DocumentSet__UserGroup
from onyx.db.models import FederatedConnector__DocumentSet
from onyx.db.models import LLMProvider__UserGroup
from onyx.db.models import PermissionGrant
from onyx.db.models import Persona
from onyx.db.models import Persona__UserGroup
from onyx.db.models import TokenRateLimit__UserGroup
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.db.models import UserGroup
from onyx.db.models import UserGroup__ConnectorCredentialPair
from onyx.db.permissions import recompute_permissions_for_group__no_commit
from onyx.db.permissions import recompute_user_permissions__no_commit
from onyx.db.users import fetch_user_by_id
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
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


def fetch_user_group(db_session: Session, user_group_id: int) -> UserGroup | None:
    stmt = select(UserGroup).where(UserGroup.id == user_group_id)
    return db_session.scalar(stmt)


def _add_user_group_snapshot_eager_loads(
    stmt: Select,
) -> Select:
    """Add eager loading options needed by UserGroup.from_model snapshot creation."""
    return stmt.options(
        selectinload(UserGroup.users),
        selectinload(UserGroup.user_group_relationships),
        selectinload(UserGroup.cc_pair_relationships)
        .selectinload(UserGroup__ConnectorCredentialPair.cc_pair)
        .options(
            selectinload(ConnectorCredentialPair.connector),
            selectinload(ConnectorCredentialPair.credential).selectinload(
                Credential.user
            ),
        ),
        selectinload(UserGroup.document_sets).options(
            selectinload(DocumentSet.connector_credential_pairs).selectinload(
                ConnectorCredentialPair.connector
            ),
            selectinload(DocumentSet.users),
            selectinload(DocumentSet.groups),
            selectinload(DocumentSet.federated_connectors).selectinload(
                FederatedConnector__DocumentSet.federated_connector
            ),
        ),
        selectinload(UserGroup.personas).options(
            selectinload(Persona.tools),
            selectinload(Persona.hierarchy_nodes),
            selectinload(Persona.attached_documents).selectinload(
                Document.parent_hierarchy_node
            ),
            selectinload(Persona.labels),
            selectinload(Persona.document_sets).options(
                selectinload(DocumentSet.connector_credential_pairs).selectinload(
                    ConnectorCredentialPair.connector
                ),
                selectinload(DocumentSet.users),
                selectinload(DocumentSet.groups),
                selectinload(DocumentSet.federated_connectors).selectinload(
                    FederatedConnector__DocumentSet.federated_connector
                ),
            ),
            selectinload(Persona.user),
            selectinload(Persona.user_files),
            selectinload(Persona.users),
            selectinload(Persona.groups),
        ),
    )


def fetch_user_groups(
    db_session: Session,
    only_up_to_date: bool = True,
    eager_load_for_snapshot: bool = False,
    include_default: bool = True,
    restrict_to_group_ids: set[int] | None = None,
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
        eager_load_for_snapshot: If True, adds eager loading for all relationships
            needed by UserGroup.from_model snapshot creation.
        include_default: If False, excludes system default groups (is_default=True).
        restrict_to_group_ids: If provided, limits the result to these group ids — the
            scoped-manager variant passes the groups they manage. An empty set returns
            nothing (fail-closed); ``None`` returns all groups (admin/global).

    Returns:
        Sequence[UserGroup]: A sequence of `UserGroup` objects matching the query criteria.
    """
    stmt = select(UserGroup)
    if only_up_to_date:
        stmt = stmt.where(UserGroup.is_up_to_date == True)  # noqa: E712
    if not include_default:
        stmt = stmt.where(UserGroup.is_default == False)  # noqa: E712
    if restrict_to_group_ids is not None:
        stmt = stmt.where(UserGroup.id.in_(restrict_to_group_ids))
    if eager_load_for_snapshot:
        stmt = _add_user_group_snapshot_eager_loads(stmt)
    return db_session.scalars(stmt).unique().all()


def fetch_user_groups_for_user(
    db_session: Session,
    user_id: UUID,
    eager_load_for_snapshot: bool = False,
    include_default: bool = True,
) -> Sequence[UserGroup]:
    stmt = (
        select(UserGroup)
        .join(User__UserGroup, User__UserGroup.user_group_id == UserGroup.id)
        .join(
            User,
            User.id == User__UserGroup.user_id,  # ty: ignore[invalid-argument-type]
        )
        .where(User.id == user_id)  # ty: ignore[invalid-argument-type]
    )
    if not include_default:
        stmt = stmt.where(UserGroup.is_default == False)  # noqa: E712
    if eager_load_for_snapshot:
        stmt = _add_user_group_snapshot_eager_loads(stmt)
    return db_session.scalars(stmt).unique().all()


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

    return db_session.execute(stmt).all()  # ty: ignore[invalid-return-type]


def _check_user_group_is_modifiable(user_group: UserGroup) -> None:
    if not user_group.is_up_to_date:
        raise ValueError(
            "Specified user group is currently syncing. Wait until the current sync has finished before editing."
        )


def _add_user__user_group_relationships__no_commit(
    db_session: Session, user_group_id: int, user_ids: list[UUID]
) -> None:
    """NOTE: does not commit the transaction.

    This function is idempotent - it will skip users who are already in the group
    to avoid duplicate key violations during concurrent operations or re-syncs.
    Uses ON CONFLICT DO NOTHING to keep inserts atomic under concurrency.
    """
    if not user_ids:
        return

    insert_stmt = (
        insert(User__UserGroup)
        .values(
            [
                {"user_id": user_id, "user_group_id": user_group_id}
                for user_id in user_ids
            ]
        )
        .on_conflict_do_nothing(
            index_elements=[User__UserGroup.user_group_id, User__UserGroup.user_id]
        )
    )
    db_session.execute(insert_stmt)


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
        name=user_group.name,
        time_last_modified_by_user=func.now(),
        is_up_to_date=DISABLE_VECTOR_DB,
    )
    db_session.add(db_user_group)
    db_session.flush()  # give the group an ID

    # Every group gets the "basic" permission by default
    db_session.add(
        PermissionGrant(
            group_id=db_user_group.id,
            permission=Permission.BASIC_ACCESS,
            grant_source=GrantSource.SYSTEM,
        )
    )
    db_session.flush()

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

    recompute_user_permissions__no_commit(user_group.user_ids, db_session)

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


def _current_cc_pair_ids(db_user_group: UserGroup) -> list[int]:
    """The cc_pairs currently attached to the group — is_current junction rows only.

    A removed cc_pair keeps a stale ``is_current=False`` row until the Vespa sync
    deletes it, and the plain ``cc_pairs`` relationship has no is_current filter, so
    it would still surface the removed pair. Reading it as "current" lets a removed
    (possibly public / out-of-scope) pair be re-attached without re-clearing the
    scope gate, so always derive the current set from the live relationships.
    """
    return [
        relationship.cc_pair_id
        for relationship in db_user_group.cc_pair_relationships
        if relationship.is_current
    ]


def add_users_to_user_group(
    db_session: Session,
    user: User,
    user_group_id: int,
    user_ids: list[UUID],
) -> UserGroup:
    db_user_group = fetch_user_group(db_session=db_session, user_group_id=user_group_id)
    if db_user_group is None:
        raise ValueError(f"UserGroup with id '{user_group_id}' not found")

    missing_users = [
        user_id for user_id in user_ids if fetch_user_by_id(db_session, user_id) is None
    ]
    if missing_users:
        raise ValueError(
            f"User(s) not found: {', '.join(str(user_id) for user_id in missing_users)}"
        )

    _check_user_group_is_modifiable(db_user_group)

    current_user_ids = [user.id for user in db_user_group.users]
    current_user_ids_set = set(current_user_ids)
    new_user_ids = [
        user_id for user_id in user_ids if user_id not in current_user_ids_set
    ]

    if not new_user_ids:
        return db_user_group

    user_group_update = UserGroupUpdate(
        user_ids=current_user_ids + new_user_ids,
        cc_pair_ids=_current_cc_pair_ids(db_user_group),
    )

    return update_user_group(
        db_session=db_session,
        user=user,
        user_group_id=user_group_id,
        user_group_update=user_group_update,
    )


def _assert_group_update_within_scope(
    db_session: Session,
    user: User,
    user_group_id: int,
    added_cc_pair_ids: set[int],
) -> None:
    """GATE 2 for a scoped manager editing a group: the group must be one they
    manage, and every newly-attached cc_pair must be a private one within their
    managed scope — otherwise the junction rewrite could attach a public or
    out-of-scope connector to the group, granting its members access. Admins /
    global holders bypass both checks."""
    assert_manages_group(user, db_session, group_id=user_group_id)

    # The cc_pair re-attach vector only applies to scoped managers; a global
    # MANAGE_USER_GROUPS holder keeps today's unrestricted attach behavior.
    if (
        has_permission(user, Permission.MANAGE_USER_GROUPS)
        is not PermissionAuthority.SCOPED
    ):
        return

    current_groups_by_cc_pair: dict[int, list[int]] = defaultdict(list)
    for row in get_cc_pair_groups_for_ids(db_session, list(added_cc_pair_ids)):
        if row.is_current and row.cc_pair_id is not None:
            current_groups_by_cc_pair[row.cc_pair_id].append(row.user_group_id)

    for cc_pair_id in added_cc_pair_ids:
        cc_pair = get_connector_credential_pair_from_id(
            db_session=db_session, cc_pair_id=cc_pair_id
        )
        if cc_pair is None:
            raise OnyxError(
                OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                "Group managers can only attach connectors within the groups they manage.",
            )
        assert_within_scope(
            user,
            db_session,
            permission=Permission.MANAGE_CONNECTORS,
            current_group_ids=current_groups_by_cc_pair[cc_pair_id],
            requested_group_ids=[user_group_id],
            is_non_public=cc_pair.access_type != AccessType.PUBLIC,
        )


def update_user_group(
    db_session: Session,
    user: User,
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

    current_cc_pair_ids = set(_current_cc_pair_ids(db_user_group))
    requested_cc_pair_ids = set(user_group_update.cc_pair_ids)
    _assert_group_update_within_scope(
        db_session,
        user,
        user_group_id,
        added_cc_pair_ids=requested_cc_pair_ids - current_cc_pair_ids,
    )

    current_user_ids = set([user.id for user in db_user_group.users])
    updated_user_ids = set(user_group_update.user_ids)
    added_user_ids = list(updated_user_ids - current_user_ids)
    removed_user_ids = list(current_user_ids - updated_user_ids)

    if added_user_ids:
        missing_users = [
            user_id
            for user_id in added_user_ids
            if fetch_user_by_id(db_session, user_id) is None
        ]
        if missing_users:
            raise ValueError(
                f"User(s) not found: {', '.join(str(user_id) for user_id in missing_users)}"
            )

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

    cc_pairs_updated = current_cc_pair_ids != requested_cc_pair_ids
    if cc_pairs_updated:
        _mark_user_group__cc_pair_relationships_outdated__no_commit(
            db_session=db_session, user_group_id=user_group_id
        )
        _add_user_group__cc_pair_relationships__no_commit(
            db_session=db_session,
            user_group_id=db_user_group.id,
            cc_pair_ids=user_group_update.cc_pair_ids,
        )

    if cc_pairs_updated and not DISABLE_VECTOR_DB:
        db_user_group.is_up_to_date = False

    # update "time_updated" to now
    db_user_group.time_last_modified_by_user = func.now()

    recompute_user_permissions__no_commit(
        list(set(added_user_ids) | set(removed_user_ids)), db_session
    )

    db_session.commit()
    return db_user_group


def _set_group_manager__no_commit(
    db_session: Session, *, user_id: UUID, group_id: int, is_manager: bool
) -> None:
    edge = db_session.scalar(
        select(User__UserGroup).where(
            User__UserGroup.user_id == user_id,
            User__UserGroup.user_group_id == group_id,
        )
    )
    if edge is None:
        raise ValueError(f"User '{user_id}' is not a member of group '{group_id}'")
    edge.is_manager = is_manager
    # Refresh the affected user's cached is_group_manager flag; a pure manager flip
    # (no membership change) otherwise leaves the route-gate flag stale.
    recompute_user_permissions__no_commit([user_id], db_session)


def make_group_manager(db_session: Session, user_id: UUID, group_id: int) -> None:
    """Flip is_manager=true on the (user, group) edge. The row must already exist —
    a manager is always a member — else ValueError. Idempotent. Does NOT commit."""
    _set_group_manager__no_commit(
        db_session, user_id=user_id, group_id=group_id, is_manager=True
    )


def revoke_group_manager(db_session: Session, user_id: UUID, group_id: int) -> None:
    """Flip is_manager=false on the (user, group) edge. The row must exist else
    ValueError. Idempotent. Does NOT commit."""
    _set_group_manager__no_commit(
        db_session, user_id=user_id, group_id=group_id, is_manager=False
    )


def rename_user_group(
    db_session: Session,
    user_group_id: int,
    new_name: str,
) -> UserGroup:
    stmt = select(UserGroup).where(UserGroup.id == user_group_id)
    db_user_group = db_session.scalar(stmt)
    if db_user_group is None:
        raise ValueError(f"UserGroup with id '{user_group_id}' not found")

    _check_user_group_is_modifiable(db_user_group)

    db_user_group.name = new_name
    db_user_group.time_last_modified_by_user = func.now()

    # CC pair documents in Vespa contain the group name, so we need to
    # trigger a sync to update them with the new name.
    _mark_user_group__cc_pair_relationships_outdated__no_commit(
        db_session=db_session, user_group_id=user_group_id
    )
    if not DISABLE_VECTOR_DB:
        db_user_group.is_up_to_date = False

    db_session.commit()
    return db_user_group


def prepare_user_group_for_deletion(db_session: Session, user_group_id: int) -> None:
    stmt = select(UserGroup).where(UserGroup.id == user_group_id)
    db_user_group = db_session.scalar(stmt)
    if db_user_group is None:
        raise ValueError(f"UserGroup with id '{user_group_id}' not found")

    _check_user_group_is_modifiable(db_user_group)

    # Collect affected user IDs before cleanup deletes the relationships
    affected_user_ids: list[UUID] = [
        uid
        for uid in db_session.execute(
            select(User__UserGroup.user_id).where(
                User__UserGroup.user_group_id == user_group_id
            )
        )
        .scalars()
        .all()
        if uid is not None
    ]

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

    # Recompute permissions for affected users now that their
    # membership in this group has been removed
    recompute_user_permissions__no_commit(affected_user_ids, db_session)

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


def set_group_permission__no_commit(
    group_id: int,
    permission: Permission,
    enabled: bool,
    granted_by: UUID,
    db_session: Session,
) -> None:
    """Grant or revoke a single permission for a group using soft-delete.

    Does NOT commit — caller must commit the session.
    """
    existing = db_session.execute(
        select(PermissionGrant)
        .where(
            PermissionGrant.group_id == group_id,
            PermissionGrant.permission == permission,
        )
        .with_for_update()
    ).scalar_one_or_none()

    if enabled:
        if existing is not None:
            if existing.is_deleted:
                existing.is_deleted = False
                existing.granted_by = granted_by
                existing.granted_at = func.now()
        else:
            db_session.add(
                PermissionGrant(
                    group_id=group_id,
                    permission=permission,
                    grant_source=GrantSource.USER,
                    granted_by=granted_by,
                )
            )
    else:
        if existing is not None and not existing.is_deleted:
            existing.is_deleted = True

    db_session.flush()
    recompute_permissions_for_group__no_commit(group_id, db_session)


def set_group_permissions_bulk__no_commit(
    group_id: int,
    desired_permissions: set[Permission],
    granted_by: UUID,
    db_session: Session,
) -> list[Permission]:
    """Set the full desired permission state for a group in one pass.

    Enables permissions in `desired_permissions`, disables any toggleable
    permission not in the set. Non-toggleable permissions are ignored.
    Calls recompute once at the end. Does NOT commit.

    Returns the resulting list of enabled permissions.
    """

    existing_grants = (
        db_session.execute(
            select(PermissionGrant)
            .where(PermissionGrant.group_id == group_id)
            .with_for_update()
        )
        .scalars()
        .all()
    )

    grant_map: dict[Permission, PermissionGrant] = {
        g.permission: g for g in existing_grants
    }

    # Enable desired permissions
    for perm in desired_permissions:
        existing = grant_map.get(perm)
        if existing is not None:
            if existing.is_deleted:
                existing.is_deleted = False
                existing.granted_by = granted_by
                existing.granted_at = func.now()
        else:
            db_session.add(
                PermissionGrant(
                    group_id=group_id,
                    permission=perm,
                    grant_source=GrantSource.USER,
                    granted_by=granted_by,
                )
            )

    # Disable toggleable permissions not in the desired set
    for perm, grant in grant_map.items():
        if perm not in desired_permissions and not grant.is_deleted:
            grant.is_deleted = True

    db_session.flush()
    recompute_permissions_for_group__no_commit(group_id, db_session)

    # Return the resulting enabled set
    return [
        g.permission
        for g in db_session.execute(
            select(PermissionGrant).where(
                PermissionGrant.group_id == group_id,
                PermissionGrant.is_deleted.is_(False),
            )
        )
        .scalars()
        .all()
    ]
