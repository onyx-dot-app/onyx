import uuid

from fastapi_users.password import PasswordHelper
from sqlalchemy import select
from sqlalchemy.orm import Session

from danswer.auth.schemas import UserRole
from danswer.configs.constants import DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN
from danswer.configs.constants import DANSWER_API_KEY_PREFIX
from danswer.configs.constants import UNNAMED_KEY_PLACEHOLDER
from danswer.db.models import ApiKey
from danswer.db.models import User
from ee.danswer.auth.api_key import ApiKeyDescriptor
from ee.danswer.auth.api_key import build_displayable_api_key
from ee.danswer.auth.api_key import generate_api_key
from ee.danswer.auth.api_key import hash_api_key
from ee.danswer.server.api_key.models import APIKeyArgs


def is_api_key_email_address(email: str) -> bool:
    return email.endswith(f"{DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN}")


def fetch_api_keys(db_session: Session) -> list[ApiKeyDescriptor]:
    api_keys = db_session.scalars(select(ApiKey)).all()
    return [
        ApiKeyDescriptor(
            api_key_id=api_key.id,
            api_key_display=api_key.api_key_display,
            api_key_name=api_key.name,
            user_id=api_key.user_id,
        )
        for api_key in api_keys
    ]


def fetch_user_for_api_key(hashed_api_key: str, db_session: Session) -> User | None:
    api_key = db_session.scalar(
        select(ApiKey).where(ApiKey.hashed_api_key == hashed_api_key)
    )
    if api_key is None:
        return None

    return db_session.scalar(select(User).where(User.id == api_key.user_id))  # type: ignore


def get_api_key_fake_email(
    name: str,
    unique_id: str,
) -> str:
    return f"{DANSWER_API_KEY_PREFIX}{name}@{unique_id}{DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN}"


def insert_api_key(
    db_session: Session, api_key_args: APIKeyArgs, user_id: uuid.UUID | None
) -> ApiKeyDescriptor:
    std_password_helper = PasswordHelper()
    api_key = generate_api_key()
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
        role=UserRole.BASIC,
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

    db_session.commit()
    return ApiKeyDescriptor(
        api_key_id=api_key_row.id,
        api_key_display=api_key_row.api_key_display,
        api_key=api_key,
        api_key_name=api_key_args.name,
        user_id=api_key_user_id,
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
    db_session.commit()

    return ApiKeyDescriptor(
        api_key_id=existing_api_key.id,
        api_key_display=existing_api_key.api_key_display,
        api_key_name=api_key_args.name,
        user_id=existing_api_key.user_id,
    )


def regenerate_api_key(db_session: Session, api_key_id: int) -> ApiKeyDescriptor:
    """NOTE: currently, any admin can regenerate any API key."""
    existing_api_key = db_session.scalar(select(ApiKey).where(ApiKey.id == api_key_id))
    if existing_api_key is None:
        raise ValueError(f"API key with id {api_key_id} does not exist")

    new_api_key = generate_api_key()
    existing_api_key.hashed_api_key = hash_api_key(new_api_key)
    existing_api_key.api_key_display = build_displayable_api_key(new_api_key)
    db_session.commit()

    return ApiKeyDescriptor(
        api_key_id=existing_api_key.id,
        api_key_display=existing_api_key.api_key_display,
        api_key=new_api_key,
        api_key_name=existing_api_key.name,
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
    db_session.delete(user_associated_with_key)
    db_session.commit()
