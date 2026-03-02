"""HTTP server for Teams bot using aiohttp + Bot Framework adapter."""

import sys

from aiohttp import web
from botbuilder.core import BotFrameworkAdapter  # type: ignore[import-untyped]
from botbuilder.core import BotFrameworkAdapterSettings
from botbuilder.core import TurnContext
from botbuilder.schema import Activity  # type: ignore[import-untyped]

from onyx.configs.app_configs import TEAMS_BOT_PORT
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.teams_bot import get_teams_bot_config
from onyx.onyxbot.teams.bot import OnyxTeamsBot
from onyx.onyxbot.teams.constants import BOT_HEALTH_ENDPOINT
from onyx.onyxbot.teams.constants import BOT_MESSAGES_ENDPOINT
from onyx.onyxbot.teams.utils import get_bot_credentials_from_env
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _get_credentials() -> tuple[str, str, str | None] | None:
    """Get bot credentials from env vars or database.

    Env vars take priority. Falls back to DB config for self-hosted
    deployments that configure via admin UI.
    """
    env_creds = get_bot_credentials_from_env()
    if env_creds:
        return env_creds

    # Try database (for self-hosted deployments)
    try:
        from onyx.db.engine.tenant_utils import get_all_tenant_ids

        tenant_ids = get_all_tenant_ids()
        for tenant_id in tenant_ids:
            with get_session_with_tenant(tenant_id=tenant_id) as db:
                config = get_teams_bot_config(db)
                if config:
                    # Access the decrypted value
                    app_secret = config.app_secret
                    if isinstance(app_secret, str):
                        return config.app_id, app_secret, config.azure_tenant_id
    except Exception as e:
        logger.warning(f"Failed to load Teams bot config from DB: {e}")

    return None


async def _handle_messages(request: web.Request) -> web.Response:
    """Handle incoming Bot Framework Activities at POST /api/messages."""
    bot: OnyxTeamsBot = request.app["bot"]
    adapter: BotFrameworkAdapter = request.app["adapter"]

    if request.content_type != "application/json":
        return web.Response(status=415, text="Unsupported media type")

    body = await request.json()
    activity = Activity().deserialize(body)

    auth_header = request.headers.get("Authorization", "")

    async def _turn_callback(turn_context: TurnContext) -> None:
        await bot.on_turn(turn_context)

    try:
        await adapter.process_activity(activity, auth_header, _turn_callback)
        return web.Response(status=200)
    except Exception as e:
        logger.exception(f"Error processing activity: {e}")
        return web.Response(status=500, text="Internal server error")


async def _handle_health(request: web.Request) -> web.Response:
    """Health check endpoint."""
    bot: OnyxTeamsBot = request.app["bot"]
    healthy = bot.api_client.is_initialized and bot.cache.is_initialized
    if healthy:
        return web.Response(status=200, text="OK")
    return web.Response(status=503, text="Not ready")


async def _on_startup(app: web.Application) -> None:
    """Initialize bot on server startup."""
    bot: OnyxTeamsBot = app["bot"]
    await bot.initialize()
    logger.info("Teams bot server started")


async def _on_shutdown(app: web.Application) -> None:
    """Shut down bot on server shutdown."""
    bot: OnyxTeamsBot = app["bot"]
    await bot.shutdown()
    logger.info("Teams bot server stopped")


def create_app(
    app_id: str,
    app_secret: str,
) -> web.Application:
    """Create the aiohttp web application for the Teams bot."""
    settings = BotFrameworkAdapterSettings(
        app_id=app_id,
        app_password=app_secret,
    )
    adapter = BotFrameworkAdapter(settings)

    bot = OnyxTeamsBot()

    app = web.Application()
    app["bot"] = bot
    app["adapter"] = adapter
    app.router.add_post(BOT_MESSAGES_ENDPOINT, _handle_messages)
    app.router.add_get(BOT_HEALTH_ENDPOINT, _handle_health)
    app.on_startup.append(_on_startup)
    app.on_shutdown.append(_on_shutdown)

    return app


def main() -> None:
    """Entry point for the Teams bot process."""
    logger.info("Starting Teams bot...")

    credentials = _get_credentials()
    if not credentials:
        logger.error(
            "Teams bot credentials not configured. "
            "Set TEAMS_BOT_APP_ID and TEAMS_BOT_APP_SECRET environment variables, "
            "or configure via the admin panel."
        )
        sys.exit(1)

    app_id, app_secret, _azure_tenant_id = credentials
    logger.info(f"Teams bot starting with App ID: {app_id}")

    app = create_app(app_id, app_secret)
    web.run_app(app, host="0.0.0.0", port=TEAMS_BOT_PORT)


if __name__ == "__main__":
    main()
