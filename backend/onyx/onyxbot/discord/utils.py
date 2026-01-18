from onyx.configs.app_configs import AUTH_TYPE
from onyx.configs.app_configs import DISCORD_BOT_TOKEN
from onyx.configs.constants import AuthType
from onyx.db.discord_bot import get_discord_bot_config
from onyx.db.engine.sql_engine import get_session_with_tenant
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
