import hashlib
import struct
from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID

from fastapi_users.password import PasswordHelper
from sqlalchemy import Select, case, delete, func, literal, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, lazyload, selectinload
from sqlalchemy.sql import expression
from sqlalchemy.sql.elements import ColumnElement, KeyedColumnElement
from sqlalchemy.sql.expression import or_

from onyx.auth.invited_users import remove_user_from_invited_users
from onyx.configs.constants import (
    ANONYMOUS_USER_EMAIL,
    DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN,
    NO_AUTH_PLACEHOLDER_USER_EMAIL,
    SLACK_SERVICE_ACCOUNT_EMAIL,
)
from onyx.db.enums import AccountType, Permission
from onyx.db.models import (
    DocumentSet,
    DocumentSet__User,
    MCPConnectionConfig,
    MCPServer,
    OAuthAccount,
    PermissionGrant,
    Persona,
    Persona__User,
    SamlAccount,
    User,
    User__ExternalUserGroupId,
    User__UserGroup,
    UserGroup,
)
from onyx.db.permissions import recompute_user_permissions__no_commit
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.models import UserGroupInfo
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

DEFAULT_ADMIN_GROUP_NAME = "Admin"
DEFAULT_BASIC_GROUP_NAME = "Basic"

_MAX_LISTED_STRANDED_EMAILS = 3

# tenant-hashed so tenants don't block each other and the id can't collide with
# the other advisory locks in the codebase
_MEMBERSHIP_LOCK_NAMESPACE = "onyx_membership_lock"


def is_limited_user(user: User) -> bool:
    """Check if a user is effectively limited — i.e. should be denied
    access by ``current_user`` and should not receive default-group
    membership.

    A user is limited when they are:
    * an anonymous user, or
    * a service account with no effective permissions (no group membership).
    """
    if user.account_type == AccountType.ANONYMOUS:
        return True
    if (
        user.account_type == AccountType.SERVICE_ACCOUNT
        and not user.effective_permissions
    ):
        return True
    return False


def user_is_admin(user: User) -> bool:
    """Return True if the user holds the full admin permission.

    Derived from effective_permissions, which is itself maintained from
    group membership — Admin-group members carry FULL_ADMIN_PANEL_ACCESS.
    """
    return Permission.FULL_ADMIN_PANEL_ACCESS.value in (
        user.effective_permissions or []
    )


def _active_admin_user_stmt() -> Select[tuple[User]]:
    """Active human admins — API-key dummies and system placeholders excluded. Admin is
    the FULL_ADMIN_PANEL_ACCESS permission now, not a role. Keep in step with
    ``_add_live_user_count_where_clause(only_admin_users=True)`` in ``db/auth.py``, which
    can't be reused here: auth -> api_key -> users is an import cycle."""
    email_col: KeyedColumnElement[Any] = User.__table__.c.email
    is_active_col: KeyedColumnElement[Any] = User.__table__.c.is_active
    return select(User).where(
        is_active_col.is_(True),
        User.effective_permissions.contains([Permission.FULL_ADMIN_PANEL_ACCESS.value]),
        expression.not_(email_col.endswith(DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN)),
        email_col != ANONYMOUS_USER_EMAIL,
        email_col != NO_AUTH_PLACEHOLDER_USER_EMAIL,
    )


def get_active_admin_users(db_session: Session) -> list[User]:
    return list(db_session.execute(_active_admin_user_stmt()).unique().scalars().all())


def group_grants_full_admin(db_session: Session, group_id: int) -> bool:
    return (
        db_session.scalar(
            select(PermissionGrant.id).where(
                PermissionGrant.group_id == group_id,
                PermissionGrant.permission == Permission.FULL_ADMIN_PANEL_ACCESS,
                PermissionGrant.is_deleted.is_(False),
            )
        )
        is not None
    )


def another_admin_survives(
    db_session: Session, group_id: int, removed_user_ids: list[UUID]
) -> bool:
    """Reads grants, not ``effective_permissions``, which still reflects the removal.

    Exclusions mirror ``_active_admin_user_stmt`` — keep the two in step."""
    email_col: KeyedColumnElement[Any] = User.__table__.c.email
    is_active_col: KeyedColumnElement[Any] = User.__table__.c.is_active
    stmt = (
        select(User__UserGroup.user_id)
        .join(
            PermissionGrant,
            PermissionGrant.group_id == User__UserGroup.user_group_id,
        )
        .join(
            User,
            User.id == User__UserGroup.user_id,  # ty: ignore[invalid-argument-type]
        )
        .where(
            PermissionGrant.permission == Permission.FULL_ADMIN_PANEL_ACCESS,
            PermissionGrant.is_deleted.is_(False),
            is_active_col.is_(True),
            expression.not_(email_col.endswith(DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN)),
            email_col != ANONYMOUS_USER_EMAIL,
            email_col != NO_AUTH_PLACEHOLDER_USER_EMAIL,
            or_(
                User__UserGroup.user_group_id != group_id,
                User__UserGroup.user_id.not_in(removed_user_ids),
            ),
        )
        .limit(1)
    )
    return db_session.scalar(stmt) is not None


def _membership_lock_id(tenant_id: str) -> int:
    digest = hashlib.sha256(
        f"{_MEMBERSHIP_LOCK_NAMESPACE}:{tenant_id}".encode()
    ).digest()
    # pg_advisory_xact_lock takes a signed 8-byte int.
    return struct.unpack("q", digest[:8])[0]


def lock_group_membership(db_session: Session) -> None:
    """One lock for every membership write, admin access included, released on the
    caller's commit. Take it before reading state the write depends on: a stale read
    misses a concurrent add, and two removals each see the other survive. Splitting it
    per class would only buy a lock order to get wrong."""
    # Bounded wait: a wedged holder should fail fast, not hang the request.
    db_session.execute(text("SET LOCAL lock_timeout = '10s'"))
    db_session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_id)"),
        {"lock_id": _membership_lock_id(get_current_tenant_id())},
    )
    db_session.execute(text("SET LOCAL lock_timeout = DEFAULT"))


def assert_admin_access_survives_removal(
    db_session: Session,
    actor: User,
    group_id: int,
    removed_user_ids: list[UUID],
) -> None:
    """Guards against locking the workspace out of its own admin panel.

    Shared by the CE admin-access endpoint and the EE group editor — same rows."""
    if not removed_user_ids or not group_grants_full_admin(db_session, group_id):
        return

    if actor.id in removed_user_ids:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "You can't remove yourself from the admin group. Ask another admin to do it.",
        )

    lock_group_membership(db_session)

    if not another_admin_survives(db_session, group_id, removed_user_ids):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "You can't remove the last admin. Grant another user admin access first.",
        )


def _stranded_by_removal(
    db_session: Session, group_id: int, removed_user_ids: list[UUID]
) -> list[str]:
    """Emails of the standard users this removal would leave in no group."""
    surviving_member_ids = set(
        db_session.scalars(
            select(User__UserGroup.user_id)
            .join(UserGroup, UserGroup.id == User__UserGroup.user_group_id)
            .where(
                User__UserGroup.user_id.in_(removed_user_ids),
                User__UserGroup.user_group_id != group_id,
                UserGroup.is_up_for_deletion.is_(False),
            )
        ).all()
    )
    stranded_ids = [
        user_id for user_id in removed_user_ids if user_id not in surviving_member_ids
    ]
    if not stranded_ids:
        return []

    email_col: KeyedColumnElement[Any] = User.__table__.c.email
    return list(
        db_session.scalars(
            select(email_col)
            .where(
                User.id.in_(stranded_ids),  # ty: ignore[unresolved-attribute]
                User.account_type == AccountType.STANDARD,
            )
            .order_by(email_col)
        ).all()
    )


def assert_group_membership_survives_removal(
    db_session: Session,
    group_id: int,
    removed_user_ids: list[UUID],
) -> None:
    """Blocks removals that leave a standard user in no group: permissions come only
    from group grants, so they would keep a login that can do nothing."""
    if not removed_user_ids:
        return

    lock_group_membership(db_session)

    stranded_emails = _stranded_by_removal(db_session, group_id, removed_user_ids)
    if not stranded_emails:
        return

    listed = ", ".join(stranded_emails[:_MAX_LISTED_STRANDED_EMAILS])
    remainder = len(stranded_emails) - _MAX_LISTED_STRANDED_EMAILS
    if remainder > 0:
        listed = f"{listed} and {remainder} more"
    raise OnyxError(
        OnyxErrorCode.INVALID_INPUT,
        f"{listed} would be left without a group. Add them to another group first.",
    )


def fetch_default_group(db_session: Session, name: str) -> UserGroup:
    group = db_session.scalar(
        select(UserGroup).where(UserGroup.name == name, UserGroup.is_default.is_(True))
    )
    if group is None:
        raise RuntimeError(
            f"Default group '{name}' not found. "
            "Ensure the seed_default_groups migration has run."
        )
    return group


def set_user_admin_access(
    db_session: Session,
    actor: User,
    target: User,
    is_admin: bool,
) -> None:
    """Toggles seeded Admin group membership — admin *is* that membership now.

    Replaces the removed ``PATCH /manage/set-user-role``. Editing groups directly is
    EE-only, which strands Community on whichever user registered first."""
    if target.account_type in (
        AccountType.BOT,
        AccountType.EXT_PERM_USER,
        AccountType.ANONYMOUS,
        AccountType.SERVICE_ACCOUNT,
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Can't change admin access for a {target.account_type.value} account.",
        )

    admin_group = fetch_default_group(db_session, DEFAULT_ADMIN_GROUP_NAME)
    membership_stmt = select(User__UserGroup).where(
        User__UserGroup.user_id == target.id,
        User__UserGroup.user_group_id == admin_group.id,
    )
    membership = db_session.scalar(membership_stmt)

    if is_admin:
        if membership is not None:
            return
        db_session.add(User__UserGroup(user_id=target.id, user_group_id=admin_group.id))
    else:
        if membership is None:
            return
        assert_admin_access_survives_removal(
            db_session, actor, admin_group.id, [target.id]
        )
        assert_group_membership_survives_removal(
            db_session, admin_group.id, [target.id]
        )
        db_session.delete(membership)

    db_session.flush()
    recompute_user_permissions__no_commit(target.id, db_session)
    db_session.commit()


def get_all_users(
    db_session: Session,
    email_filter_string: str | None = None,
    include_external: bool = False,
    include_api_key_users: bool = True,
) -> Sequence[User]:
    """List all users. No pagination as of now, as the # of users
    is assumed to be relatively small (<< 1 million)"""
    # Override the default joined-eager load of oauth_accounts: a selectin load
    # avoids multiplying user rows and fetching the (potentially large) OAuth
    # token columns, while still populating the collection so that
    # User.password_configured works.
    stmt = select(User).options(
        selectinload(User.oauth_accounts).load_only(
            OAuthAccount.id  # ty: ignore[invalid-argument-type]
        )
    )

    # Exclude system users (anonymous user, no-auth placeholder)
    stmt = stmt.where(
        User.email != ANONYMOUS_USER_EMAIL  # ty: ignore[invalid-argument-type]
    )
    stmt = stmt.where(
        User.email != NO_AUTH_PLACEHOLDER_USER_EMAIL  # ty: ignore[invalid-argument-type]
    )

    if not include_external:
        stmt = stmt.where(User.account_type != AccountType.EXT_PERM_USER)

    if not include_api_key_users:
        stmt = stmt.where(
            expression.not_(
                User.__table__.c.email.endswith(DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN)
            )
        )

    if email_filter_string is not None:
        stmt = stmt.where(
            User.email.ilike(  # ty: ignore[unresolved-attribute]
                f"%{email_filter_string}%"
            )
        )

    return db_session.scalars(stmt).unique().all()


def _get_accepted_user_where_clause(
    email_filter_string: str | None = None,
    include_external: bool = False,
    is_active_filter: bool | None = None,
    account_type_filter: list[AccountType] | None = None,
) -> list[ColumnElement[bool]]:
    """
    Generates a SQLAlchemy where clause for filtering users based on the provided parameters.
    This is used to build the filters for the function that retrieves the users for the users table in the admin panel.

    Parameters:
    - email_filter_string: A substring to filter user emails. Only users whose emails contain this substring will be included.
    - is_active_filter: When True, only active users will be included. When False, only inactive users will be included.
    - include_external: If False, external permissioned users will be excluded.
    - account_type_filter: If provided and non-empty, only users whose ``account_type`` is in the list will be included.

    Returns:
    - list: A list of conditions to be used in a SQLAlchemy query to filter users.
    """

    # Access table columns directly via __table__.c to get proper SQLAlchemy column types
    # This ensures type checking works correctly for SQL operations like ilike, endswith, and is_
    email_col: KeyedColumnElement[Any] = User.__table__.c.email
    is_active_col: KeyedColumnElement[Any] = User.__table__.c.is_active

    where_clause: list[ColumnElement[bool]] = [
        expression.not_(email_col.endswith(DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN)),
        # Exclude system users (anonymous user, no-auth placeholder)
        email_col != ANONYMOUS_USER_EMAIL,
        email_col != NO_AUTH_PLACEHOLDER_USER_EMAIL,
    ]

    if not include_external:
        where_clause.append(User.account_type != AccountType.EXT_PERM_USER)

    if email_filter_string is not None:
        personal_name_col: KeyedColumnElement[Any] = User.__table__.c.personal_name
        where_clause.append(
            or_(
                email_col.ilike(f"%{email_filter_string}%"),
                personal_name_col.ilike(f"%{email_filter_string}%"),
            )
        )

    if is_active_filter is not None:
        where_clause.append(is_active_col.is_(is_active_filter))

    if account_type_filter:
        where_clause.append(User.account_type.in_(account_type_filter))

    return where_clause


def get_all_accepted_users(
    db_session: Session,
    include_external: bool = False,
) -> Sequence[User]:
    """Returns all accepted users without pagination.
    Uses the same filtering as the paginated endpoint but without
    search or active filters."""
    stmt = select(User)
    where_clause = _get_accepted_user_where_clause(
        include_external=include_external,
    )
    stmt = stmt.where(*where_clause).order_by(User.email)
    return db_session.scalars(stmt).unique().all()


def get_page_of_filtered_users(
    db_session: Session,
    page_size: int,
    page_num: int,
    email_filter_string: str | None = None,
    is_active_filter: bool | None = None,
    include_external: bool = False,
    account_type_filter: list[AccountType] | None = None,
) -> Sequence[User]:
    users_stmt = select(User)

    where_clause = _get_accepted_user_where_clause(
        email_filter_string=email_filter_string,
        include_external=include_external,
        is_active_filter=is_active_filter,
        account_type_filter=account_type_filter,
    )
    # Apply pagination
    users_stmt = users_stmt.offset((page_num) * page_size).limit(page_size)
    # Apply filtering
    users_stmt = users_stmt.where(*where_clause)

    return db_session.scalars(users_stmt).unique().all()


def get_total_filtered_users_count(
    db_session: Session,
    email_filter_string: str | None = None,
    is_active_filter: bool | None = None,
    include_external: bool = False,
    account_type_filter: list[AccountType] | None = None,
) -> int:
    where_clause = _get_accepted_user_where_clause(
        email_filter_string=email_filter_string,
        include_external=include_external,
        is_active_filter=is_active_filter,
        account_type_filter=account_type_filter,
    )
    total_count_stmt = select(func.count()).select_from(User)
    # Apply filtering
    total_count_stmt = total_count_stmt.where(*where_clause)

    return db_session.scalar(total_count_stmt) or 0


def get_user_counts_by_account_type_and_status(
    db_session: Session,
) -> dict[str, dict[str, int]]:
    """Returns user counts grouped by account_type and by active/inactive status.

    Excludes API key users, anonymous users, and no-auth placeholder users.
    Uses a single query with conditional aggregation.
    """
    base_where = _get_accepted_user_where_clause()
    account_type_col = User.__table__.c.account_type
    is_active_col = User.__table__.c.is_active

    stmt = (
        select(
            account_type_col,
            func.count().label("total"),
            func.sum(case((is_active_col.is_(True), 1), else_=0)).label("active"),
            func.sum(case((is_active_col.is_(False), 1), else_=0)).label("inactive"),
        )
        .where(*base_where)
        .group_by(account_type_col)
    )

    account_type_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {"active": 0, "inactive": 0}

    for account_type_val, total, active, inactive in db_session.execute(stmt).all():
        key = (
            account_type_val.value
            if hasattr(account_type_val, "value")
            else str(account_type_val)
        )
        account_type_counts[key] = total
        status_counts["active"] += active or 0
        status_counts["inactive"] += inactive or 0

    return {
        "account_type_counts": account_type_counts,
        "status_counts": status_counts,
    }


def get_user_by_email(email: str, db_session: Session) -> User | None:
    user = (
        db_session.query(User)
        .filter(func.lower(User.email) == func.lower(email))
        .first()
    )
    return user


def get_user_by_oauth_account(
    oauth_name: str, account_id: str, db_session: Session
) -> User | None:
    """Find a user by the IdP subject their account is linked to.

    Unlike the email lookup, this keeps working after an IdP rename.
    """
    return (
        db_session.query(User)
        .join(
            OAuthAccount,
            OAuthAccount.user_id == User.id,  # ty: ignore[invalid-argument-type]
        )
        .filter(
            OAuthAccount.oauth_name == oauth_name,  # ty: ignore[invalid-argument-type]
            OAuthAccount.account_id == account_id,  # ty: ignore[invalid-argument-type]
        )
        .first()
    )


def build_email_reconcile_update(user: User, new_email: str) -> dict[str, Any] | None:
    """Fields that move `user` onto `new_email`, or None when they already match
    case-insensitively.

    The replaced address is kept in `prior_emails`, which keeps matching the
    documents whose indexed ACLs still name it.
    """
    current_email = user.email.lower()
    new_email = new_email.lower()
    if current_email == new_email:
        return None

    # Re-adopting an old address makes it current, so it stops being an alias.
    kept = [
        email.lower()
        for email in user.prior_emails
        if email.lower() not in (new_email, current_email)
    ]
    return {"email": new_email, "prior_emails": [*kept, current_email]}


def reconcile_user_email__no_commit(
    user_id: UUID, new_email: str, db_session: Session
) -> tuple[str, list[str]] | None:
    """Move a user and their email-keyed rows in one transaction.

    Rows are locked so a concurrent login builds `prior_emails` from the latest
    address. Returns None when the address was already current, which does not
    mean nothing changed: a shadow user may still have been merged in.
    """
    normalized_new_email = new_email.lower()
    users = (
        db_session.query(User)
        .filter(
            or_(
                User.id == user_id,  # ty: ignore[invalid-argument-type]
                func.lower(User.email) == normalized_new_email,
            )
        )
        .order_by(User.id)  # ty: ignore[invalid-argument-type]
        .populate_existing()
        .with_for_update(of=User)
        .all()
    )
    user = next((candidate for candidate in users if candidate.id == user_id), None)
    if user is None:
        raise ValueError(f"User {user_id} disappeared during email reconciliation")

    shadow_user = next(
        (
            candidate
            for candidate in users
            if candidate.id != user_id
            and candidate.account_type == AccountType.EXT_PERM_USER
            and not candidate.oauth_accounts
        ),
        None,
    )
    if shadow_user is not None:
        membership_insert = pg_insert(User__ExternalUserGroupId).from_select(
            ["user_id", "external_user_group_id", "cc_pair_id", "stale"],
            select(
                literal(user_id),
                User__ExternalUserGroupId.external_user_group_id,
                User__ExternalUserGroupId.cc_pair_id,
                User__ExternalUserGroupId.stale,
            ).where(User__ExternalUserGroupId.user_id == shadow_user.id),
        )
        db_session.execute(
            membership_insert.on_conflict_do_update(
                index_elements=[
                    User__ExternalUserGroupId.user_id,
                    User__ExternalUserGroupId.external_user_group_id,
                    User__ExternalUserGroupId.cc_pair_id,
                ],
                set_={
                    "stale": User__ExternalUserGroupId.stale
                    & membership_insert.excluded.stale
                },
            )
        )
        db_session.execute(
            delete(User__ExternalUserGroupId).where(
                User__ExternalUserGroupId.user_id == shadow_user.id
            )
        )
        db_session.delete(shadow_user)
        db_session.flush()
        logger.info(
            "Merged external-permission shadow user %s into user %s",
            shadow_user.id,
            user_id,
        )

    email_update = build_email_reconcile_update(user, normalized_new_email)
    if email_update is None:
        return None

    old_email = user.email
    prior_emails = list(email_update["prior_emails"])

    user.email = normalized_new_email
    user.prior_emails = prior_emails
    db_session.execute(
        update(MCPServer)
        .where(MCPServer.owner == old_email)
        .values(owner=normalized_new_email)
    )
    db_session.execute(
        update(MCPConnectionConfig)
        .where(MCPConnectionConfig.user_email == old_email)
        .values(user_email=normalized_new_email)
    )
    return old_email, prior_emails


def fetch_users_by_ids(db_session: Session, user_ids: list[UUID]) -> list[User]:
    """Missing ids are absent from the result; callers diff to name them."""
    if not user_ids:
        return []
    return list(
        db_session.scalars(
            select(User).where(
                User.id.in_(user_ids)  # ty: ignore[unresolved-attribute]
            )
        )
        .unique()
        .all()
    )


def fetch_user_by_id(
    db_session: Session, user_id: UUID, for_update: bool = False
) -> User | None:
    """``for_update`` adds ``SELECT ... FOR UPDATE``, serializing concurrent
    transactions that use the user row as a reservation boundary (e.g. Craft
    sandbox/session reservation). Hold only for a short transaction."""
    query = db_session.query(User).filter(
        User.id == user_id  # ty: ignore[invalid-argument-type]
    )
    if for_update:
        # oauth_accounts is lazy="joined"; Postgres forbids FOR UPDATE on the
        # nullable side of an outer join, so defer it when locking.
        query = query.options(lazyload(User.oauth_accounts)).with_for_update()
    return query.first()


def _generate_password_hash() -> str:
    password_helper = PasswordHelper()
    return password_helper.hash(password_helper.generate())


def _generate_slack_user(email: str) -> User:
    return User(
        email=email,
        hashed_password=_generate_password_hash(),
        account_type=AccountType.BOT,
    )


def add_slack_user_if_not_exists(
    db_session: Session,
    email: str,
    enforce_seat_check: Callable[[Session, int], None] | None = None,
) -> User:
    """Look up or create the Slack-bot user for ``email``.

    ``enforce_seat_check`` (optional): invoked inside this function's
    transaction whenever the call would consume a seat — i.e. on
    brand-new BOT creation OR on EXT_PERM_USER (uncounted) -> BOT
    (counted) promotion. Must raise on overage.
    """
    email = email.lower()
    user = get_user_by_email(email, db_session)
    if user is not None:
        # If the user is an external permissioned user, we update it to a slack user
        if user.account_type == AccountType.EXT_PERM_USER:
            if enforce_seat_check is not None:
                enforce_seat_check(db_session, 1)
            user.account_type = AccountType.BOT
            db_session.commit()
        return user

    if enforce_seat_check is not None:
        enforce_seat_check(db_session, 1)
    user = _generate_slack_user(email=email)
    db_session.add(user)
    db_session.commit()
    return user


def get_or_create_slack_service_account(db_session: Session) -> User:
    user = get_user_by_email(SLACK_SERVICE_ACCOUNT_EMAIL, db_session)
    if user is not None:
        return user

    user = User(
        email=SLACK_SERVICE_ACCOUNT_EMAIL,
        hashed_password=_generate_password_hash(),
        is_active=True,
        is_verified=True,
        account_type=AccountType.SERVICE_ACCOUNT,
    )
    db_session.add(user)
    try:
        db_session.commit()
        return user
    except IntegrityError:
        db_session.rollback()
        concurrent_user = get_user_by_email(SLACK_SERVICE_ACCOUNT_EMAIL, db_session)
        if concurrent_user is None:
            raise
        return concurrent_user


def _get_users_by_emails(
    db_session: Session, lower_emails: list[str]
) -> tuple[list[User], list[str]]:
    """given a list of lowercase emails,
    returns a list[User] of Users whose emails match and a list[str]
    the missing emails that had no User"""
    stmt = select(User).filter(func.lower(User.email).in_(lower_emails))
    found_users = list(db_session.scalars(stmt).unique().all())  # Convert to list

    # Extract found emails and convert to lowercase to avoid case sensitivity issues
    found_users_emails = [user.email.lower() for user in found_users]

    # Separate emails for users that were not found
    missing_user_emails = [
        email for email in lower_emails if email not in found_users_emails
    ]
    return found_users, missing_user_emails


def _generate_ext_permissioned_user(email: str) -> User:
    fastapi_users_pw_helper = PasswordHelper()
    password = fastapi_users_pw_helper.generate()
    hashed_pass = fastapi_users_pw_helper.hash(password)
    return User(
        email=email,
        hashed_password=hashed_pass,
        account_type=AccountType.EXT_PERM_USER,
    )


def batch_add_ext_perm_user_if_not_exists(
    db_session: Session, emails: list[str], continue_on_error: bool = False
) -> list[User]:
    lower_emails = [email.lower() for email in emails]
    found_users, missing_lower_emails = _get_users_by_emails(db_session, lower_emails)

    # Use savepoints (begin_nested) so that a failed insert only rolls back
    # that single user, not the entire transaction. A plain rollback() would
    # discard all previously flushed users in the same transaction.
    # We also avoid add_all() because SQLAlchemy 2.0's insertmanyvalues
    # batch path hits a UUID sentinel mismatch with server_default columns.
    for email in missing_lower_emails:
        user = _generate_ext_permissioned_user(email=email)
        savepoint = db_session.begin_nested()
        try:
            db_session.add(user)
            savepoint.commit()
        except IntegrityError:
            savepoint.rollback()
            if not continue_on_error:
                raise

    db_session.commit()
    # Fetch all users again to ensure we have the most up-to-date list
    all_users, _ = _get_users_by_emails(db_session, lower_emails)
    return all_users


def assign_user_to_default_groups__no_commit(
    db_session: Session,
    user: User,
    is_admin: bool = False,
) -> None:
    """Assign a newly created user to the appropriate default group.

    Does NOT commit — callers must commit the session themselves so that
    group assignment can be part of the same transaction as user creation.

    Args:
        is_admin: If True, assign to Admin default group; otherwise Basic.
            Callers determine this from their own context (e.g. user_count,
            admin email list, explicit choice). Defaults to False (Basic).
    """
    if user.account_type in (
        AccountType.BOT,
        AccountType.EXT_PERM_USER,
        AccountType.ANONYMOUS,
    ):
        return

    target_group_name = (
        DEFAULT_ADMIN_GROUP_NAME if is_admin else DEFAULT_BASIC_GROUP_NAME
    )

    default_group = (
        db_session.query(UserGroup)
        .filter(
            UserGroup.name == target_group_name,
            UserGroup.is_default.is_(True),
        )
        .first()
    )

    if default_group is None:
        raise RuntimeError(
            f"Default group '{target_group_name}' not found. "
            f"Cannot assign user {user.email} to a group. "
            f"Ensure the seed_default_groups migration has run."
        )

    # Check if the user is already in the group
    existing = (
        db_session.query(User__UserGroup)
        .filter(
            User__UserGroup.user_id == user.id,
            User__UserGroup.user_group_id == default_group.id,
        )
        .first()
    )
    if existing is not None:
        return

    savepoint = db_session.begin_nested()
    try:
        db_session.add(
            User__UserGroup(
                user_id=user.id,
                user_group_id=default_group.id,
            )
        )
        db_session.flush()
    except IntegrityError:
        # Race condition: another transaction inserted this membership
        # between our SELECT and INSERT. The savepoint isolates the failure
        # so the outer transaction (user creation) stays intact.
        savepoint.rollback()
        return

    from onyx.db.permissions import recompute_user_permissions__no_commit

    recompute_user_permissions__no_commit(user.id, db_session)

    logger.info(
        "Assigned user %s to default group '%s'", user.email, default_group.name
    )


def get_active_admin_count(db_session: Session) -> int:
    """Count for the share dialog's Admins row — same filter set as
    get_active_admin_users (no API-key dummies or system placeholders).
    Runs on the hot GET /persona/{id} path, so count in SQL rather than
    materializing every admin row."""
    stmt = select(func.count()).select_from(_active_admin_user_stmt().subquery())
    return db_session.execute(stmt).scalar_one()


def delete_user_from_db__no_commit(
    user_to_delete: User,
    db_session: Session,
) -> None:
    for oauth_account in user_to_delete.oauth_accounts:
        db_session.delete(oauth_account)

    fetch_ee_implementation_or_noop(
        "onyx.db.external_perm",
        "delete_user__ext_group_for_user__no_commit",
    )(
        db_session=db_session,
        user_id=user_to_delete.id,
    )
    db_session.query(SamlAccount).filter(
        SamlAccount.user_id == user_to_delete.id
    ).delete()
    # Null out ownership on document sets so they're preserved for other
    # users instead of being cascade-deleted
    db_session.query(DocumentSet).filter(
        DocumentSet.user_id == user_to_delete.id
    ).update({DocumentSet.user_id: None})
    # Personas: private ones die with their owner; shared/public ones are
    # orphaned (ownerless ⇒ managed by admins until transferred away)
    owned_personas = (
        db_session.query(Persona)
        .options(
            selectinload(Persona.user_shares),
            selectinload(Persona.group_shares),
        )
        .filter(Persona.user_id == user_to_delete.id)
        .all()
    )
    for persona in owned_personas:
        if (
            not persona.is_public
            and not persona.user_shares
            and not persona.group_shares
        ):
            persona.deleted = True
        persona.user_id = None

    db_session.query(DocumentSet__User).filter(
        DocumentSet__User.user_id == user_to_delete.id
    ).delete()
    db_session.query(Persona__User).filter(
        Persona__User.user_id == user_to_delete.id
    ).delete()
    db_session.query(User__UserGroup).filter(
        User__UserGroup.user_id == user_to_delete.id
    ).delete()
    db_session.delete(user_to_delete)


def delete_user_from_db(
    user_to_delete: User,
    db_session: Session,
) -> None:
    delete_user_from_db__no_commit(user_to_delete, db_session)
    db_session.commit()

    # NOTE: edge case may exist with race conditions
    # with this `invited user` scheme generally.
    remove_user_from_invited_users(user_to_delete.email)


def batch_get_user_groups(
    db_session: Session,
    user_ids: list[UUID],
    include_default: bool = False,
) -> dict[UUID, list[tuple[int, str]]]:
    """Fetch group memberships for a batch of users in a single query.
    Returns a mapping of user_id -> list of (group_id, group_name) tuples."""
    if not user_ids:
        return {}

    stmt = (
        select(
            User__UserGroup.user_id,
            UserGroup.id,
            UserGroup.name,
        )
        .join(UserGroup, UserGroup.id == User__UserGroup.user_group_id)
        .where(User__UserGroup.user_id.in_(user_ids))
    )
    if not include_default:
        stmt = stmt.where(UserGroup.is_default == False)  # noqa: E712

    rows = db_session.execute(stmt).all()

    result: dict[UUID, list[tuple[int, str]]] = {uid: [] for uid in user_ids}
    for user_id, group_id, group_name in rows:
        result[user_id].append((group_id, group_name))
    return result


def get_user_groups(
    db_session: Session,
    user_id: UUID,
    include_default: bool = False,
) -> list[UserGroupInfo]:
    """Lightweight group info for a single user."""
    return [
        UserGroupInfo(id=gid, name=gname)
        for gid, gname in batch_get_user_groups(
            db_session, [user_id], include_default=include_default
        ).get(user_id, [])
    ]


def set_user_groups__no_commit(
    db_session: Session,
    user_id: UUID,
    group_ids: list[int],
) -> None:
    """Replace all group memberships for a user with the given group_ids.
    Does NOT commit."""
    if group_ids:
        existing_ids = set(
            db_session.scalars(
                select(UserGroup.id).where(UserGroup.id.in_(group_ids))
            ).all()
        )
        missing = set(group_ids) - existing_ids
        if missing:
            raise ValueError(f"Group IDs do not exist: {sorted(missing)}")

    db_session.execute(
        delete(User__UserGroup).where(User__UserGroup.user_id == user_id)
    )

    if group_ids:
        insert_stmt = (
            pg_insert(User__UserGroup)
            .values([{"user_id": user_id, "user_group_id": gid} for gid in group_ids])
            .on_conflict_do_nothing(
                index_elements=[User__UserGroup.user_group_id, User__UserGroup.user_id]
            )
        )
        db_session.execute(insert_stmt)

    recompute_user_permissions__no_commit(user_id, db_session)
