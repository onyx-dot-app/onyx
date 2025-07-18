from telebot.async_telebot import AsyncTeleBot

from . import user


def register_events(bot: AsyncTeleBot) -> None:
    user.setup(bot)
