import uuid

from fastapi_users.password import PasswordHelper
from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import Session

from onyx.auth.api_key import ApiKeyDescriptor
from onyx.auth.api_key import build_displayable_api_key
from onyx.auth.api_key import generate_api_key
from onyx.auth.api_key import hash_api_key
from onyx.configs.constants import DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN
from onyx.configs.constants import DANSWER_API_KEY_PREFIX
from onyx.configs.constants import UNNAMED_KEY_PLACEHOLDER
from onyx.db.enums import AccountType
from onyx.db.models import ApiKey
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.db.models import UserGroup
from onyx.db.permissions import recompute_user_permissions__no_commit
from onyx.server.api_key.models import APIKeyArgs
from onyx.server.models import UserGroupInfo
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


def get_api_key_email_pattern() -> str:
    return DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN


def is_api_key_email_address(email: str) -> bool:
    return email.endswith(get_api_key_email_pattern())


def _get_user_groups(db_session: Session, user_id: uuid.UUID) -> list[UserGroupInfo]:
    """Get lightweight group info for a user."""
    groups = (
        db_session.scalars(
            select(UserGroup)
            .join(User__UserGroup, User__UserGroup.user_group_id == UserGroup.id)
            .where(User__UserGroup.user_id == user_id)
        )
        .unique()
        .all()
    )
    return [UserGroupInfo(id=g.id, name=g.name) for g in groups]


def _get_user_groups_by_user_ids(
    db_session: Session, user_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[UserGroupInfo]]:
    """Batch-fetch group memberships for multiple users in a single query."""
    if not user_ids:
        return {}

    rows = db_session.execute(
        select(User__UserGroup.user_id, UserGroup.id, UserGroup.name)
        .join(UserGroup, UserGroup.id == User__UserGroup.user_group_id)
        .where(User__UserGroup.user_id.in_(user_ids))
    ).all()

    groups_by_user: dict[uuid.UUID, list[UserGroupInfo]] = {}
    for user_id, group_id, group_name in rows:
        groups_by_user.setdefault(user_id, []).append(
            UserGroupInfo(id=group_id, name=group_name)
        )
    return groups_by_user


def _set_user_groups__no_commit(
    db_session: Session,
    user_id: uuid.UUID,
    group_ids: list[int],
) -> None:
    """Replace all group memberships for a user with the given group_ids.
    Does NOT commit."""
    if group_ids:
        # Validate that all requested group IDs exist
        existing_ids = set(
            db_session.scalars(
                select(UserGroup.id).where(UserGroup.id.in_(group_ids))
            ).all()
        )
        missing = set(group_ids) - existing_ids
        if missing:
            raise ValueError(f"Group IDs do not exist: {sorted(missing)}")

    # Remove all existing memberships
    db_session.execute(
        delete(User__UserGroup).where(User__UserGroup.user_id == user_id)
    )

    # Add new memberships
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


def fetch_api_keys(db_session: Session) -> list[ApiKeyDescriptor]:
    api_keys = (
        db_session.scalars(select(ApiKey).options(joinedload(ApiKey.user)))
        .unique()
        .all()
    )
    groups_by_user = _get_user_groups_by_user_ids(
        db_session, [api_key.user_id for api_key in api_keys]
    )
    return [
        ApiKeyDescriptor(
            api_key_id=api_key.id,
            api_key_display=api_key.api_key_display,
            api_key_name=api_key.name,
            user_id=api_key.user_id,
            groups=groups_by_user.get(api_key.user_id, []),
        )
        for api_key in api_keys
    ]


async def fetch_user_for_api_key(
    hashed_api_key: str, async_db_session: AsyncSession
) -> User | None:
    """NOTE: this is async, since it's used during auth
    (which is necessarily async due to FastAPI Users)"""
    return await async_db_session.scalar(
        select(User)
        .join(ApiKey, ApiKey.user_id == User.id)
        .where(ApiKey.hashed_api_key == hashed_api_key)
    )


def get_api_key_fake_email(
    name: str,
    unique_id: str,
) -> str:
    return f"{DANSWER_API_KEY_PREFIX}{name}@{unique_id}{DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN}"


def insert_api_key(
    db_session: Session, api_key_args: APIKeyArgs, user_id: uuid.UUID | None
) -> ApiKeyDescriptor:
    std_password_helper = PasswordHelper()

    # Get tenant_id from context var (will be default schema for single tenant)
    tenant_id = get_current_tenant_id()

    api_key = generate_api_key(tenant_id)
    api_key_user_id = uuid.uuid4()

    display_name = api_key_args.name or UNNAMED_KEY_PLACEHOLDER
    api_key_user_row = User(
        id=api_key_user_id,
        email=get_api_key_fake_email(display_name, str(api_key_user_id)),
        # a random password for the "user"
        hashed_password=std_password_helper.hash(std_password_helper.generate()),
        is_active=True,
        is_superuser=False,
        is_verified=True,
        account_type=AccountType.SERVICE_ACCOUNT,
    )
    db_session.add(api_key_user_row)

    api_key_row = ApiKey(
        name=api_key_args.name,
        hashed_api_key=hash_api_key(api_key),
        api_key_display=build_displayable_api_key(api_key),
        user_id=api_key_user_id,
        owner_id=user_id,
    )
    db_session.add(api_key_row)

    # Assign the service account to the specified groups
    _set_user_groups__no_commit(db_session, api_key_user_id, api_key_args.group_ids)

    db_session.commit()

    return ApiKeyDescriptor(
        api_key_id=api_key_row.id,
        api_key_display=api_key_row.api_key_display,
        api_key=api_key,
        api_key_name=api_key_args.name,
        user_id=api_key_user_id,
        groups=_get_user_groups(db_session, api_key_user_id),
    )


def update_api_key(
    db_session: Session, api_key_id: int, api_key_args: APIKeyArgs
) -> ApiKeyDescriptor:
    existing_api_key = db_session.scalar(select(ApiKey).where(ApiKey.id == api_key_id))
    if existing_api_key is None:
        raise ValueError(f"API key with id {api_key_id} does not exist")

    existing_api_key.name = api_key_args.name
    api_key_user = db_session.scalar(
        select(User).where(User.id == existing_api_key.user_id)  # type: ignore
    )
    if api_key_user is None:
        raise RuntimeError("API Key does not have associated user.")

    email_name = api_key_args.name or UNNAMED_KEY_PLACEHOLDER
    api_key_user.email = get_api_key_fake_email(email_name, str(api_key_user.id))

    # Replace all group memberships with the specified groups
    _set_user_groups__no_commit(db_session, api_key_user.id, api_key_args.group_ids)

    db_session.commit()

    return ApiKeyDescriptor(
        api_key_id=existing_api_key.id,
        api_key_display=existing_api_key.api_key_display,
        api_key_name=api_key_args.name,
        user_id=existing_api_key.user_id,
        groups=_get_user_groups(db_session, existing_api_key.user_id),
    )


def regenerate_api_key(db_session: Session, api_key_id: int) -> ApiKeyDescriptor:
    """NOTE: currently, any admin can regenerate any API key."""
    existing_api_key = db_session.scalar(select(ApiKey).where(ApiKey.id == api_key_id))
    if existing_api_key is None:
        raise ValueError(f"API key with id {api_key_id} does not exist")

    api_key_user = db_session.scalar(
        select(User).where(User.id == existing_api_key.user_id)  # type: ignore
    )
    if api_key_user is None:
        raise RuntimeError("API Key does not have associated user.")

    # Get tenant_id from context var (will be default schema for single tenant)
    tenant_id = get_current_tenant_id()

    new_api_key = generate_api_key(tenant_id)
    existing_api_key.hashed_api_key = hash_api_key(new_api_key)
    existing_api_key.api_key_display = build_displayable_api_key(new_api_key)
    db_session.commit()

    return ApiKeyDescriptor(
        api_key_id=existing_api_key.id,
        api_key_display=existing_api_key.api_key_display,
        api_key=new_api_key,
        api_key_name=existing_api_key.name,
        user_id=existing_api_key.user_id,
        groups=_get_user_groups(db_session, existing_api_key.user_id),
    )


def remove_api_key(db_session: Session, api_key_id: int) -> None:
    existing_api_key = db_session.scalar(select(ApiKey).where(ApiKey.id == api_key_id))
    if existing_api_key is None:
        raise ValueError(f"API key with id {api_key_id} does not exist")

    user_associated_with_key = db_session.scalar(
        select(User).where(User.id == existing_api_key.user_id)  # type: ignore
    )
    if user_associated_with_key is None:
        raise ValueError(
            f"User associated with API key with id {api_key_id} does not exist. This should not happen."
        )

    db_session.delete(existing_api_key)
    db_session.delete(user_associated_with_key)
    db_session.commit()
