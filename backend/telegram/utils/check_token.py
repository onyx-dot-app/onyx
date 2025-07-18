import asyncio

from telebot.async_telebot import AsyncTeleBot

import os
import sys

from onyx.server.features.telegram.store import load_telegram_settings


async def check_token(current_token: str, bot: AsyncTeleBot):
    while True:
        token = load_telegram_settings()

        if token.token != current_token:
            await bot.delete_webhook()
            await bot.close_session()
            await bot.close()
            os.execv(sys.executable, ['python'] + sys.argv)
        await asyncio.sleep(15)
