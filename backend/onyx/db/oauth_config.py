from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import OAuthConfig
from onyx.db.models import OAuthUserToken
from onyx.db.models import Tool
from onyx.utils.logger import setup_logger


logger = setup_logger()


# OAuth Config CRUD operations


def create_oauth_config(
    name: str,
    authorization_url: str,
    token_url: str,
    client_id: str,
    client_secret: str,
    scopes: list[str] | None,
    additional_params: dict[str, str] | None,
    db_session: Session,
) -> OAuthConfig:
    """Create a new OAuth configuration"""
    oauth_config = OAuthConfig(
        name=name,
        authorization_url=authorization_url,
        token_url=token_url,
        client_id=client_id,
        client_secret=client_secret,
        scopes=scopes,
        additional_params=additional_params,
    )
    db_session.add(oauth_config)
    db_session.commit()
    return oauth_config


def get_oauth_config(oauth_config_id: int, db_session: Session) -> OAuthConfig | None:
    """Get OAuth configuration by ID"""
    return db_session.scalar(
        select(OAuthConfig).where(OAuthConfig.id == oauth_config_id)
    )


def get_oauth_configs(db_session: Session) -> list[OAuthConfig]:
    """Get all OAuth configurations"""
    return list(db_session.scalars(select(OAuthConfig)).all())


def update_oauth_config(
    oauth_config_id: int,
    db_session: Session,
    name: str | None = None,
    authorization_url: str | None = None,
    token_url: str | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
    scopes: list[str] | None = None,
    additional_params: dict[str, Any] | None = None,
    clear_client_id: bool = False,
    clear_client_secret: bool = False,
) -> OAuthConfig:
    """
    Update OAuth configuration.

    NOTE: If client_id or client_secret are None, existing values are preserved.
    To clear these values, set clear_client_id or clear_client_secret to True.
    This allows partial updates without re-entering secrets.
    """
    oauth_config = db_session.scalar(
        select(OAuthConfig).where(OAuthConfig.id == oauth_config_id)
    )
    if oauth_config is None:
        raise ValueError(f"OAuth config with id {oauth_config_id} does not exist")

    # Update only provided fields
    if name is not None:
        oauth_config.name = name
    if authorization_url is not None:
        oauth_config.authorization_url = authorization_url
    if token_url is not None:
        oauth_config.token_url = token_url
    if clear_client_id:
        oauth_config.client_id = ""
    elif client_id is not None:
        oauth_config.client_id = client_id
    if clear_client_secret:
        oauth_config.client_secret = ""
    elif client_secret is not None:
        oauth_config.client_secret = client_secret
    if scopes is not None:
        oauth_config.scopes = scopes
    if additional_params is not None:
        oauth_config.additional_params = additional_params

    db_session.commit()
    return oauth_config


def delete_oauth_config(oauth_config_id: int, db_session: Session) -> None:
    """
    Delete OAuth configuration.

    Sets oauth_config_id to NULL for associated tools due to SET NULL foreign key.
    Cascades delete to user tokens.
    """
    oauth_config = db_session.scalar(
        select(OAuthConfig).where(OAuthConfig.id == oauth_config_id)
    )
    if oauth_config is None:
        raise ValueError(f"OAuth config with id {oauth_config_id} does not exist")

    db_session.delete(oauth_config)
    db_session.commit()


# User Token operations


def get_user_oauth_token(
    oauth_config_id: int, user_id: UUID, db_session: Session
) -> OAuthUserToken | None:
    """Get user's OAuth token for a specific configuration"""
    return db_session.scalar(
        select(OAuthUserToken).where(
            OAuthUserToken.oauth_config_id == oauth_config_id,
            OAuthUserToken.user_id == user_id,
        )
    )


def upsert_user_oauth_token(
    oauth_config_id: int, user_id: UUID, token_data: dict, db_session: Session
) -> OAuthUserToken:
    """Insert or update user's OAuth token for a specific configuration"""
    existing_token = get_user_oauth_token(oauth_config_id, user_id, db_session)

    if existing_token:
        # Update existing token
        existing_token.token_data = token_data
        db_session.commit()
        return existing_token
    else:
        # Create new token
        new_token = OAuthUserToken(
            oauth_config_id=oauth_config_id,
            user_id=user_id,
            token_data=token_data,
        )
        db_session.add(new_token)
        db_session.commit()
        return new_token


def delete_user_oauth_token(
    oauth_config_id: int, user_id: UUID, db_session: Session
) -> None:
    """Delete user's OAuth token for a specific configuration"""
    user_token = get_user_oauth_token(oauth_config_id, user_id, db_session)
    if user_token is None:
        raise ValueError(
            f"OAuth token for user {user_id} and config {oauth_config_id} does not exist"
        )

    db_session.delete(user_token)
    db_session.commit()


# Helper operations


def get_tools_by_oauth_config(oauth_config_id: int, db_session: Session) -> list[Tool]:
    """Get all tools that use a specific OAuth configuration"""
    return list(
        db_session.scalars(
            select(Tool).where(Tool.oauth_config_id == oauth_config_id)
        ).all()
    )
