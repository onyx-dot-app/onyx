from sqlalchemy.orm import Session
from telebot.async_telebot import AsyncTeleBot
from telebot.states.sync import StateContext
from telebot.types import Message

from onyx.db.telegram import check_api_token, edit_telegram_user_id_by_api_key, get_user_telegram_settings, \
    init_user_telegram_settings
from telegram.utils.database import with_session
from telegram.keyboard.settings import create_main_menu_keyboard


def handler(bot: AsyncTeleBot):
    @bot.message_handler(commands=["start"])
    @with_session
    async def handle_start(message: Message, session: Session, state: StateContext):
        user_api_key = message.text.split()[1] if len(message.text.split()) > 1 else None
        if user_api_key:
            db_from_api_key = check_api_token(user_api_key, session)
            if db_from_api_key is True:
                edit_telegram_user_id_by_api_key(user_api_key, message.from_user.id, session)

                user_settings = get_user_telegram_settings(message.from_user.id, session)

                if not user_settings:
                    init_user_telegram_settings(message.from_user.id, session)

                await bot.send_message(message.from_user.id, "Вы успешно авторизовались!")
            await bot.send_message(
                message.from_user.id,
                "Добро пожаловать! Воспользуйтесь меню для навигации:",
                reply_markup=create_main_menu_keyboard()
            )

