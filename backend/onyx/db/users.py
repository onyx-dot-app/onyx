from collections.abc import Sequence
from typing import Any
from uuid import UUID

from fastapi_users.password import PasswordHelper
from sqlalchemy import case
from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql import expression
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.elements import KeyedColumnElement
from sqlalchemy.sql.expression import or_

from onyx.auth.invited_users import remove_user_from_invited_users
from onyx.configs.constants import ANONYMOUS_USER_EMAIL
from onyx.configs.constants import DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN
from onyx.configs.constants import NO_AUTH_PLACEHOLDER_USER_EMAIL
from onyx.db.enums import AccountType
from onyx.db.enums import Permission
from onyx.db.models import DocumentSet
from onyx.db.models import DocumentSet__User
from onyx.db.models import Persona
from onyx.db.models import Persona__User
from onyx.db.models import SamlAccount
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.db.models import UserGroup
from onyx.db.permissions import recompute_user_permissions__no_commit
from onyx.server.models import UserGroupInfo
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop

logger = setup_logger()


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


def get_all_users(
    db_session: Session,
    email_filter_string: str | None = None,
    include_external: bool = False,
) -> Sequence[User]:
    """List all users. No pagination as of now, as the # of users
    is assumed to be relatively small (<< 1 million)"""
    stmt = select(User)

    # Exclude system users (anonymous user, no-auth placeholder)
    stmt = stmt.where(User.email != ANONYMOUS_USER_EMAIL)  # type: ignore
    stmt = stmt.where(User.email != NO_AUTH_PLACEHOLDER_USER_EMAIL)  # type: ignore

    if not include_external:
        stmt = stmt.where(User.account_type != AccountType.EXT_PERM_USER)

    if email_filter_string is not None:
        stmt = stmt.where(User.email.ilike(f"%{email_filter_string}%"))  # type: ignore

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


def fetch_user_by_id(db_session: Session, user_id: UUID) -> User | None:
    return db_session.query(User).filter(User.id == user_id).first()  # type: ignore


def _generate_slack_user(email: str) -> User:
    fastapi_users_pw_helper = PasswordHelper()
    password = fastapi_users_pw_helper.generate()
    hashed_pass = fastapi_users_pw_helper.hash(password)
    return User(
        email=email,
        hashed_password=hashed_pass,
        account_type=AccountType.BOT,
    )


def add_slack_user_if_not_exists(db_session: Session, email: str) -> User:
    email = email.lower()
    user = get_user_by_email(email, db_session)
    if user is not None:
        # If the user is an external permissioned user, we update it to a slack user
        if user.account_type == AccountType.EXT_PERM_USER:
            user.account_type = AccountType.BOT
            db_session.commit()
        return user

    user = _generate_slack_user(email=email)
    db_session.add(user)
    db_session.commit()
    return user


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

    target_group_name = "Admin" if is_admin else "Basic"

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

    logger.info(f"Assigned user {user.email} to default group '{default_group.name}'")


def delete_user_from_db(
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
    # Null out ownership on document sets and personas so they're
    # preserved for other users instead of being cascade-deleted
    db_session.query(DocumentSet).filter(
        DocumentSet.user_id == user_to_delete.id
    ).update({DocumentSet.user_id: None})
    db_session.query(Persona).filter(Persona.user_id == user_to_delete.id).update(
        {Persona.user_id: None}
    )

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


def get_user_groups(db_session: Session, user_id: UUID) -> list[UserGroupInfo]:
    """Lightweight group info for a single user."""
    return [
        UserGroupInfo(id=gid, name=gname)
        for gid, gname in batch_get_user_groups(db_session, [user_id]).get(user_id, [])
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
