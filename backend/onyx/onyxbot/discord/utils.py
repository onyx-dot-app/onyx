from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.auth.api_key import build_displayable_api_key
from onyx.auth.api_key import generate_api_key
from onyx.auth.api_key import hash_api_key
from onyx.auth.schemas import UserRole
from onyx.configs.app_configs import AUTH_TYPE
from onyx.configs.app_configs import DISCORD_BOT_TOKEN
from onyx.configs.constants import AuthType
from onyx.db.api_key import insert_api_key
from onyx.db.discord_bot import get_discord_bot_config
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.models import ApiKey
from onyx.db.models import User
from onyx.onyxbot.discord.constants import DISCORD_SERVICE_API_KEY_NAME
from onyx.onyxbot.discord.exceptions import APIKeyProvisioningError
from onyx.server.api_key.models import APIKeyArgs
from onyx.utils.logger import setup_logger
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA

logger = setup_logger()


def get_bot_token() -> str | None:
    """Get Discord bot token from env var or database.

    Priority:
    1. DISCORD_BOT_TOKEN env var (always takes precedence)
    2. For self-hosted: DiscordBotConfig in database (default tenant)
    3. For Cloud: should always have env var set

    Returns:
        Bot token string, or None if not configured.
    """
    # Environment variable takes precedence
    if DISCORD_BOT_TOKEN:
        return DISCORD_BOT_TOKEN

    # Cloud should always have env var; if not, return None
    if AUTH_TYPE == AuthType.CLOUD:
        logger.warning("Cloud deployment missing DISCORD_BOT_TOKEN env var")
        return None

    # Self-hosted: check database for bot config
    try:
        with get_session_with_tenant(tenant_id=POSTGRES_DEFAULT_SCHEMA) as db:
            config = get_discord_bot_config(db)
    except Exception as e:
        logger.error(f"Failed to get bot token from database: {e}")
        return None
    return config.bot_token if config else None


### API key provisioning utilities ###


def get_api_key_by_name(db_session: Session, name: str) -> ApiKey | None:
    """Get an API key by its name."""
    return db_session.scalar(select(ApiKey).where(ApiKey.name == name))


def get_or_create_discord_service_api_key(
    db_session: Session,
    tenant_id: str,
) -> str:
    """Get existing Discord service API key or create one.

    The API key is used by the Discord bot to authenticate with the
    Onyx API pods when sending chat requests.

    Args:
        db_session: Database session for the tenant.
        tenant_id: The tenant ID (used for logging/context).

    Returns:
        The raw API key string (not hashed).

    Raises:
        APIKeyProvisioningError: If API key creation fails.
    """
    # Check for existing key
    existing = get_api_key_by_name(db_session, DISCORD_SERVICE_API_KEY_NAME)
    if existing:
        # Database only stores the hash, so we must regenerate to get the raw key.
        # This is safe since the Discord bot is the only consumer of this key.
        logger.debug(
            f"Found existing Discord service API key for tenant {tenant_id} that isn't in cache, "
            "regenerating to update cache"
        )
        new_api_key = generate_api_key(tenant_id)
        existing.hashed_api_key = hash_api_key(new_api_key)
        existing.api_key_display = build_displayable_api_key(new_api_key)
        db_session.flush()
        return new_api_key

    # Create new API key
    try:
        logger.info(f"Creating Discord service API key for tenant {tenant_id}")
        api_key_args = APIKeyArgs(
            name=DISCORD_SERVICE_API_KEY_NAME,
            role=UserRole.LIMITED,  # Limited role is sufficient for chat requests
        )
        api_key_descriptor = insert_api_key(
            db_session=db_session,
            api_key_args=api_key_args,
            user_id=None,  # Service account, no owner
        )

        if not api_key_descriptor.api_key:
            raise APIKeyProvisioningError(
                f"Failed to get raw API key after creation for tenant {tenant_id}"
            )

        return api_key_descriptor.api_key

    except Exception as e:
        logger.error(f"Failed to create Discord service API key: {e}")
        raise APIKeyProvisioningError(
            f"Failed to provision API key for tenant {tenant_id}: {e}"
        ) from e


def delete_discord_service_api_key(db_session: Session, tenant_id: str) -> bool:
    """Delete the Discord service API key for a tenant.

    Called when:
    - Bot config is deleted (self-hosted)
    - All guild configs are deleted (Cloud)

    Args:
        db_session: Database session for the tenant.
        tenant_id: The tenant ID (used for logging).

    Returns:
        True if the key was deleted, False if it didn't exist.
    """
    existing_key = get_api_key_by_name(db_session, DISCORD_SERVICE_API_KEY_NAME)
    if not existing_key:
        logger.debug(f"No Discord service API key found for tenant {tenant_id}")
        return False

    # Also delete the associated user
    api_key_user = db_session.scalar(
        select(User).where(User.id == existing_key.user_id)
    )

    db_session.delete(existing_key)
    if api_key_user:
        db_session.delete(api_key_user)

    db_session.flush()
    logger.info(f"Deleted Discord service API key for tenant {tenant_id}")
    return True
