import asyncio
import os

from telebot import asyncio_filters
from telebot.async_telebot import AsyncTeleBot
from telebot.states.asyncio import StateMiddleware

from onyx.configs.app_configs import POSTGRES_API_SERVER_POOL_SIZE, POSTGRES_API_SERVER_POOL_OVERFLOW
from onyx.configs.constants import POSTGRES_WEB_APP_NAME
from onyx.db.engine import SqlEngine
from telegram.filters.auth import AuthFilter
from telegram.handlers import register_events
from telegram.utils.check_token import check_token

from onyx.server.features.telegram.models import TelegramTokenSettings
from onyx.server.features.telegram.store import load_telegram_settings, store_telegram_settings


def main() -> None:
    SqlEngine.set_app_name(POSTGRES_WEB_APP_NAME)

    SqlEngine.init_engine(
        pool_size=POSTGRES_API_SERVER_POOL_SIZE,
        max_overflow=POSTGRES_API_SERVER_POOL_OVERFLOW,
    )
    tg_settings = load_telegram_settings()
    token = tg_settings.token
    if token is None:
        token = os.environ.get("TELEGRAM_TOKEN")
        store_telegram_settings(TelegramTokenSettings(token=token))
    bot = AsyncTeleBot(
        token,
    )

    bot.add_custom_filter(AuthFilter())
    bot.setup_middleware(StateMiddleware(bot))
    bot.add_custom_filter(asyncio_filters.StateFilter(bot))
    register_events(bot)
    loop = asyncio.get_event_loop()
    try:
        loop.create_task(check_token(tg_settings.token, bot))
        loop.create_task(bot.polling(allowed_updates=["message", "callback_query"]))
        loop.run_forever()
    except (SystemExit, KeyboardInterrupt):
        pass
    finally:
        pending = asyncio.all_tasks(loop=loop)
        for task in pending:
            task.cancel()
            try:
                loop.run_until_complete(task)
            except asyncio.CancelledError:
                pass

        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


if __name__ == "__main__":
    main()
