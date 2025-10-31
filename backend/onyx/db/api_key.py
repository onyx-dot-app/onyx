import uuid

from fastapi_users.password import PasswordHelper
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import Session

from onyx.auth.api_key import ApiKeyDescriptor
from onyx.auth.api_key import build_displayable_api_key
from onyx.auth.api_key import generate_api_key
from onyx.auth.api_key import hash_api_key
from onyx.auth.schemas import ApiKeyType
from onyx.auth.schemas import UserType
from onyx.configs.constants import DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN
from onyx.configs.constants import DANSWER_API_KEY_PREFIX
from onyx.configs.constants import UNNAMED_KEY_PLACEHOLDER
from onyx.db.models import ApiKey
from onyx.db.models import User
from onyx.server.api_key.models import APIKeyArgs
from shared_configs.contextvars import get_current_tenant_id


def get_api_key_email_pattern() -> str:
    return DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN


def is_api_key_email_address(email: str) -> bool:
    return email.endswith(get_api_key_email_pattern())


def fetch_api_keys(db_session: Session) -> list[ApiKeyDescriptor]:
    api_keys = (
        db_session.scalars(select(ApiKey).options(joinedload(ApiKey.user)))
        .unique()
        .all()
    )
    return [
        ApiKeyDescriptor(
            api_key_id=api_key.id,
            api_key_role=api_key.user.role,
            api_key_type=get_api_key_type(api_key.user),
            user_email=api_key.user.email,
            api_key_display=api_key.api_key_display,
            api_key_name=api_key.name,
            user_id=api_key.user_id,
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


def is_api_key_user(user: User) -> bool:
    """Check if a user is a fake user created specifically for API key purposes.

    API keys can be backed by either:
    - Fake users (user_type=API_KEY): Created solely to represent the API key with a specific role
    - Real users (user_type=HUMAN): API key mirrors the real user's permissions

    This function returns True only for fake API key users.
    """
    return user.user_type == UserType.API_KEY


def get_api_key_type(user: User) -> ApiKeyType:
    """Determine the API key type based on the user.

    Returns:
    - ApiKeyType.SERVICE_ACCOUNT for fake API key users
    - ApiKeyType.PERSONAL_ACCESS_TOKEN for real users
    """
    if is_api_key_user(user):
        return ApiKeyType.SERVICE_ACCOUNT
    else:
        return ApiKeyType.PERSONAL_ACCESS_TOKEN


def insert_api_key(
    db_session: Session, api_key_args: APIKeyArgs, user_id: uuid.UUID | None
) -> ApiKeyDescriptor:
    # Get tenant_id from context var (will be default schema for single tenant)
    tenant_id = get_current_tenant_id()

    # Type is required when creating a new API key
    if api_key_args.type is None:
        raise ValueError("API key type is required when creating a new key")

    api_key = generate_api_key(tenant_id)

    if api_key_args.type == ApiKeyType.PERSONAL_ACCESS_TOKEN:
        # Personal Access Token: Link to real user
        api_key_user = db_session.scalar(select(User).where(User.id == user_id))
        if api_key_user is None:
            raise ValueError(f"User with id {user_id} does not exist")
    else:
        # Service Account: Create fake service account user with specific role
        if api_key_args.role is None:
            raise ValueError("Service account keys require a role")
        api_key_user = create_api_key_user(db_session, api_key_args)

    api_key_row = ApiKey(
        name=api_key_args.name,
        hashed_api_key=hash_api_key(api_key),
        api_key_display=build_displayable_api_key(api_key),
        user_id=api_key_user.id,
        owner_id=user_id,
    )
    db_session.add(api_key_row)

    db_session.commit()
    return ApiKeyDescriptor(
        api_key_id=api_key_row.id,
        api_key_role=api_key_user.role,
        api_key_type=api_key_args.type,
        user_email=api_key_user.email,
        api_key_display=api_key_row.api_key_display,
        api_key=api_key,
        api_key_name=api_key_args.name,
        user_id=api_key_user.id,
    )


def create_api_key_user(db_session: Session, api_key_args: APIKeyArgs) -> User:
    api_key_user_id = uuid.uuid4()
    std_password_helper = PasswordHelper()
    display_name = api_key_args.name or UNNAMED_KEY_PLACEHOLDER
    api_key_user = User(
        id=api_key_user_id,
        email=get_api_key_fake_email(display_name, str(api_key_user_id)),
        # a random password for the "user"
        hashed_password=std_password_helper.hash(std_password_helper.generate()),
        is_active=True,
        is_superuser=False,
        is_verified=True,
        role=api_key_args.role,
        user_type=UserType.API_KEY,
    )
    db_session.add(api_key_user)
    return api_key_user


def update_api_key(
    db_session: Session, api_key_id: int, api_key_args: APIKeyArgs
) -> ApiKeyDescriptor:
    existing_api_key = db_session.scalar(select(ApiKey).where(ApiKey.id == api_key_id))
    if existing_api_key is None:
        raise ValueError(f"API key with id {api_key_id} does not exist")

    api_key_user = db_session.scalar(
        select(User).where(User.id == existing_api_key.user_id)  # type: ignore
    )

    if api_key_user is None:
        raise RuntimeError("API Key does not have associated user.")

    # Determine the API key type
    api_key_type = get_api_key_type(api_key_user)

    # Update the API key's name
    existing_api_key.name = api_key_args.name

    if api_key_type == ApiKeyType.SERVICE_ACCOUNT:
        # Service Account: can update name, email, and role
        if api_key_args.role is None:
            raise ValueError("Service account keys require a role")

        email_name = api_key_args.name or UNNAMED_KEY_PLACEHOLDER
        api_key_user.email = get_api_key_fake_email(email_name, str(api_key_user.id))
        api_key_user.role = api_key_args.role
    else:
        # Personal Access Token: only update the API key's name, not the user's role
        if api_key_args.role is not None and api_key_args.role != api_key_user.role:
            raise ValueError(
                "Cannot update the role of API key based on the owner's role!"
            )

    db_session.commit()

    return ApiKeyDescriptor(
        api_key_id=existing_api_key.id,
        api_key_display=existing_api_key.api_key_display,
        api_key_name=api_key_args.name,
        api_key_role=api_key_user.role,
        api_key_type=api_key_type,
        user_email=api_key_user.email,
        user_id=existing_api_key.user_id,
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
        api_key_role=api_key_user.role,
        api_key_type=get_api_key_type(api_key_user),
        user_email=api_key_user.email,
        user_id=existing_api_key.user_id,
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
    if is_api_key_user(user_associated_with_key):
        # Only delete fake API key users. Do not delete real human users!
        db_session.delete(user_associated_with_key)
    db_session.commit()
