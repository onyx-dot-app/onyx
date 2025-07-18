from telebot.async_telebot import AsyncTeleBot

from telegram.handlers.user import start, settings, messaging


def setup(bot: AsyncTeleBot) -> None:
    for module in (
        start,
        settings,
        messaging
    ):
        module.handler(bot)
