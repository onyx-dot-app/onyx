from collections import defaultdict
from collections.abc import Sequence
from operator import and_
from typing import NamedTuple
from uuid import UUID

from sqlalchemy import Select, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, selectinload

from ee.onyx.server.user_group.models import (
    UserGroupCreate,
    UserGroupUpdate,
)
from onyx.auth.permissions import (
    NON_TOGGLEABLE_PERMISSIONS,
    get_effective_permissions,
    has_global_permission,
    has_permission,
    resolve_effective_permissions,
)
from onyx.auth.scoped_permissions import assert_manages_group, assert_within_scope
from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.db.connector_credential_pair import (
    get_cc_pair_groups_for_ids,
    get_connector_credential_pair_from_id,
)
from onyx.db.enums import (
    AccessType,
    AccountType,
    ConnectorCredentialPairStatus,
    GrantSource,
    Permission,
    PermissionAuthority,
)
from onyx.db.models import (
    ConnectorCredentialPair,
    Credential,
    Credential__UserGroup,
    Document,
    DocumentByConnectorCredentialPair,
    DocumentSet,
    DocumentSet__UserGroup,
    FederatedConnector__DocumentSet,
    LLMProvider__UserGroup,
    MCPServer__UserGroup,
    PermissionGrant,
    Persona,
    Persona__User,
    Persona__UserGroup,
    TokenRateLimit__UserGroup,
    User,
    User__UserGroup,
    UserGroup,
    UserGroup__ConnectorCredentialPair,
)
from onyx.db.permissions import (
    recompute_permissions_for_group__no_commit,
    recompute_user_permissions__no_commit,
)
from onyx.db.users import (
    assert_admin_access_survives_removal,
    assert_group_membership_survives_removal,
    fetch_users_by_ids,
    lock_group_membership,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.audit import (
    AuditAction,
    AuditOutcome,
    actor_from_user,
    emit_audit_event,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

_NON_GROUP_ACCOUNT_TYPES = (
    AccountType.BOT,
    AccountType.EXT_PERM_USER,
    AccountType.ANONYMOUS,
)


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


def _cleanup_mcp_server__user_group_relationships__no_commit(
    db_session: Session, user_group_id: int
) -> None:
    """NOTE: does not commit the transaction."""
    db_session.query(MCPServer__UserGroup).filter(
        MCPServer__UserGroup.user_group_id == user_group_id
    ).delete(synchronize_session=False)


def _handle_owned_personas_for_group_deletion__no_commit(
    db_session: Session, user_group_id: int
) -> None:
    """Personas owned by the group: otherwise-private ones die with it;
    shared/public ones are orphaned (ownerless ⇒ managed by admins).

    NOTE: does not commit the transaction."""
    owned_personas = (
        db_session.query(Persona)
        .options(
            selectinload(Persona.user_shares),
            selectinload(Persona.group_shares),
        )
        .filter(Persona.owner_group_id == user_group_id)
        .all()
    )
    for persona in owned_personas:
        if (
            not persona.is_public
            and not persona.user_shares
            and not persona.group_shares
        ):
            persona.deleted = True
        persona.owner_group_id = None


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
            selectinload(Persona.owner_group),
            selectinload(Persona.user_shares).selectinload(Persona__User.user),
            selectinload(Persona.group_shares).selectinload(
                Persona__UserGroup.user_group
            ),
        ),
    )


def fetch_user_group_for_snapshot(
    db_session: Session, user_group_id: int
) -> UserGroup | None:
    """Eager-loaded for UserGroup.from_model, so reading one group costs one
    query set instead of the whole tenant listing."""
    stmt = _add_user_group_snapshot_eager_loads(
        select(UserGroup).where(UserGroup.id == user_group_id)
    )
    return db_session.scalar(stmt)


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
        # OnyxError, not ValueError: the routes map ValueError to NOT_FOUND, so a
        # syncing group used to be indistinguishable from a deleted one.
        raise OnyxError(
            OnyxErrorCode.RESOURCE_SYNCING,
            "Specified user group is currently syncing. Wait until the current "
            "sync has finished before editing.",
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


def set_user_group_incognito(
    db_session: Session, user_group_id: int, enabled: bool
) -> UserGroup:
    """Flip whether members may use incognito under groups-only availability."""
    group = db_session.scalar(select(UserGroup).where(UserGroup.id == user_group_id))
    if group is None:
        raise ValueError(f"UserGroup with id '{user_group_id}' not found")
    group.incognito_enabled = enabled
    db_session.commit()
    return group


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
    # Gate before any read of the group's data so a non-manager can't confirm a
    # group exists, even on the early-return path below.
    assert_manages_group(user, db_session, group_id=user_group_id)

    lock_group_membership(db_session)

    db_user_group = fetch_user_group(db_session=db_session, user_group_id=user_group_id)
    if db_user_group is None:
        raise ValueError(f"UserGroup with id '{user_group_id}' not found")

    found_ids = {user.id for user in fetch_users_by_ids(db_session, user_ids)}
    missing_users = [user_id for user_id in user_ids if user_id not in found_ids]
    if missing_users:
        raise ValueError(
            f"User(s) not found: {', '.join(str(user_id) for user_id in missing_users)}"
        )

    _check_user_group_is_modifiable(db_user_group)
    # gate here too: the no-op early return below skips update_user_group's copy
    _assert_default_group_update_allowed(user, db_user_group, attaching_cc_pairs=False)

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


def _assert_no_privilege_amplification(
    db_session: Session,
    user: User,
    user_group_id: int,
    added_user_ids: list[UUID],
) -> None:
    """Adding a member hands them the group's grants, so a MANAGE_USER_GROUPS holder
    could otherwise join the seeded Admin group and become admin. Never blocks a
    group's own manager: a manager is always a member, so already holds its grants."""
    if not added_user_ids:
        return

    group_permissions = set(
        db_session.scalars(
            select(PermissionGrant.permission).where(
                PermissionGrant.group_id == user_group_id,
                PermissionGrant.is_deleted.is_(False),
            )
        )
    )
    # seeded into every group, so requiring it would block group-less actors
    group_permissions.discard(Permission.BASIC_ACCESS)
    excess = group_permissions - get_effective_permissions(user)
    if excess:
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "You can't add members to a group that grants permissions you don't "
            "hold: " + ", ".join(sorted(permission.value for permission in excess)),
        )


def _assert_users_can_join_groups(added_users: list[User]) -> None:
    """Only STANDARD and SERVICE_ACCOUNT enter the group system. The picker hides
    the rest, but the route accepts any uuid."""
    rejected = sorted(
        f"{added_user.email} ({added_user.account_type.value})"
        for added_user in added_users
        if added_user.account_type in _NON_GROUP_ACCOUNT_TYPES
    )
    if rejected:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "These accounts can't join a group: " + ", ".join(rejected),
        )


def _assert_default_group_update_allowed(
    user: User,
    db_user_group: UserGroup,
    *,
    attaching_cc_pairs: bool,
) -> None:
    """Members are all a default group has, and only a full admin may change them. Lives
    here because both write paths reach it, and because connectors ride in the same PATCH
    payload as membership — there is no group-side connector route to guard, unlike agents
    and document sets."""
    if not db_user_group.is_default:
        return

    if not has_global_permission(user, Permission.FULL_ADMIN_PANEL_ACCESS):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Only administrators can change the membership of a default system group.",
        )
    if attaching_cc_pairs:
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "A default system group holds only members, so it can't take connectors.",
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

    cc_pairs_by_id = {
        cc_pair.id: cc_pair
        for cc_pair in db_session.scalars(
            select(ConnectorCredentialPair).where(
                ConnectorCredentialPair.id.in_(added_cc_pair_ids)
            )
        )
    }

    for cc_pair_id in added_cc_pair_ids:
        cc_pair = cc_pairs_by_id.get(cc_pair_id)
        if cc_pair is None:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"Connector credential pair '{cc_pair_id}' not found.",
            )
        assert_within_scope(
            user,
            db_session,
            permission=Permission.MANAGE_CONNECTORS,
            current_group_ids=current_groups_by_cc_pair[cc_pair_id],
            requested_group_ids=[user_group_id],
            is_non_public=cc_pair.access_type != AccessType.PUBLIC,
        )


def _retains_group_admin_without(
    user: User, group_id: int, db_session: Session
) -> bool:
    """Whether ``user`` would still hold global MANAGE_USER_GROUPS with ``group_id`` gone.

    Reads grants directly rather than ``effective_permissions``, which still reflects the
    membership being removed."""
    granted = {
        permission.value
        for permission in db_session.scalars(
            select(PermissionGrant.permission)
            .join(
                User__UserGroup,
                User__UserGroup.user_group_id == PermissionGrant.group_id,
            )
            .where(
                User__UserGroup.user_id == user.id,
                User__UserGroup.user_group_id != group_id,
                PermissionGrant.is_deleted.is_(False),
            )
        )
    }
    return Permission.MANAGE_USER_GROUPS.value in resolve_effective_permissions(granted)


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
    # Gate before any read so a non-manager can't confirm the group exists; the
    # cc_pair scope check below needs the group row and runs after.
    assert_manages_group(user, db_session, group_id=user_group_id)

    # Locked before the reads below, adds included: an add that lands after a
    # deletion's roster snapshot is wiped by its cleanup without being checked.
    lock_group_membership(db_session)

    stmt = select(UserGroup).where(UserGroup.id == user_group_id)
    db_user_group = db_session.scalar(stmt)
    if db_user_group is None:
        raise ValueError(f"UserGroup with id '{user_group_id}' not found")

    _check_user_group_is_modifiable(db_user_group)

    current_cc_pair_ids = set(_current_cc_pair_ids(db_user_group))
    leave_cc_pairs_alone = user_group_update.cc_pair_ids is None
    requested_cc_pair_ids = (
        current_cc_pair_ids
        if leave_cc_pairs_alone
        else set(user_group_update.cc_pair_ids or [])
    )
    _assert_default_group_update_allowed(
        user,
        db_user_group,
        attaching_cc_pairs=not leave_cc_pairs_alone and bool(requested_cc_pair_ids),
    )
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

    _assert_no_privilege_amplification(db_session, user, user_group_id, added_user_ids)
    # Runs before the manager guard below so the admin-specific message wins.
    assert_admin_access_survives_removal(
        db_session, user, user_group_id, removed_user_ids
    )
    assert_group_membership_survives_removal(
        db_session, user_group_id, removed_user_ids
    )

    # Removing yourself drops the membership row carrying is_manager, and
    # effective_permissions is derived from group grants — so leaving can revoke the very
    # authority that admitted you. Allowed only when a grant survives the removal.
    if user.id in removed_user_ids and not _retains_group_admin_without(
        user, user_group_id, db_session
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "You can't remove yourself from a group you manage.",
        )

    if added_user_ids:
        added_users = fetch_users_by_ids(db_session, added_user_ids)
        found_ids = {added_user.id for added_user in added_users}
        missing_users = [
            user_id for user_id in added_user_ids if user_id not in found_ids
        ]
        if missing_users:
            raise ValueError(
                f"User(s) not found: {', '.join(str(user_id) for user_id in missing_users)}"
            )
        _assert_users_can_join_groups(added_users)

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
            cc_pair_ids=list(requested_cc_pair_ids),
        )

    if cc_pairs_updated and not DISABLE_VECTOR_DB:
        db_user_group.is_up_to_date = False

    # update "time_updated" to now
    db_user_group.time_last_modified_by_user = func.now()

    recompute_user_permissions__no_commit(
        list(set(added_user_ids) | set(removed_user_ids)), db_session
    )

    db_session.commit()

    group_name = db_user_group.name
    group_is_default = db_user_group.is_default

    # Core writes above leave the loaded ORM collections stale, and sessions run
    # expire_on_commit=False — without this the caller serializes pre-update membership.
    db_session.expire(db_user_group)

    if added_user_ids or removed_user_ids:
        emit_audit_event(
            AuditAction.USER_GROUP_CHANGE,
            AuditOutcome.SUCCESS,
            actor=actor_from_user(user),
            resource_type="user_group",
            resource_id=user_group_id,
            extra={
                "group_name": group_name,
                "is_default": group_is_default,
                "added_user_ids": [str(uid) for uid in added_user_ids],
                "removed_user_ids": [str(uid) for uid in removed_user_ids],
            },
        )

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


def assert_group_membership_survives_deletion(
    db_session: Session, user_group_id: int
) -> None:
    """Deletion drops every membership, so the strand rule covers the whole roster.
    Guards the route, not prepare_user_group_for_deletion — the sync task re-runs
    that one, and raising there would wedge a scheduled deletion."""
    # Locked first: cleanup deletes every membership, including ones added after this read.
    lock_group_membership(db_session)

    member_ids: list[UUID] = [
        user_id
        for user_id in db_session.scalars(
            select(User__UserGroup.user_id).where(
                User__UserGroup.user_group_id == user_group_id
            )
        ).all()
        if user_id is not None
    ]
    assert_group_membership_survives_removal(db_session, user_group_id, member_ids)


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
    _cleanup_mcp_server__user_group_relationships__no_commit(
        db_session=db_session, user_group_id=user_group_id
    )
    _handle_owned_personas_for_group_deletion__no_commit(
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


class PermissionChange(NamedTuple):
    """The diff is computed here, not by the caller, because this is the only place
    holding the row lock. A caller diffing before and after would race a concurrent
    save and would read whatever the ORM had already cached.
    """

    enabled: list[Permission]
    added: list[Permission]
    removed: list[Permission]


def set_group_permissions_bulk__no_commit(
    group_id: int,
    desired_permissions: set[Permission],
    granted_by: UUID,
    db_session: Session,
) -> PermissionChange:
    """Set the full desired permission state for a group in one pass.

    Enables permissions in `desired_permissions`, disables any toggleable
    permission not in the set. Non-toggleable permissions are ignored.
    Calls recompute once at the end. Does NOT commit.

    Grants are soft-deleted: revoking flips `is_deleted`, re-granting flips it back and
    re-stamps `granted_by`/`granted_at`, so a row is INSERTed only once per group and the
    grant history survives. Readers must filter `is_deleted.is_(False)`.
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

    # Non-toggleable grants (e.g. the SYSTEM basic_access every group gets) are
    # not managed here — never enabled, never disabled.
    desired_permissions = desired_permissions - NON_TOGGLEABLE_PERMISSIONS

    added: list[Permission] = []
    removed: list[Permission] = []

    # Enable desired permissions
    for perm in desired_permissions:
        existing = grant_map.get(perm)
        if existing is not None:
            if existing.is_deleted:
                existing.is_deleted = False
                existing.granted_by = granted_by
                existing.granted_at = func.now()
                added.append(perm)
        else:
            db_session.add(
                PermissionGrant(
                    group_id=group_id,
                    permission=perm,
                    grant_source=GrantSource.USER,
                    granted_by=granted_by,
                )
            )
            added.append(perm)

    # Disable toggleable permissions not in the desired set
    for perm, grant in grant_map.items():
        if (
            perm not in desired_permissions
            and perm not in NON_TOGGLEABLE_PERMISSIONS
            and not grant.is_deleted
        ):
            grant.is_deleted = True
            removed.append(perm)

    db_session.flush()
    recompute_permissions_for_group__no_commit(group_id, db_session)

    enabled = [
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
    return PermissionChange(
        enabled=enabled,
        added=sorted(added, key=lambda p: p.value),
        removed=sorted(removed, key=lambda p: p.value),
    )
