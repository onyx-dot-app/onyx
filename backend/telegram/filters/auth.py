from telebot.asyncio_filters import SimpleCustomFilter
from telebot.types import Message, CallbackQuery

from onyx.db.telegram import get_user_telegram_api_key_by_tg_user_id
from telegram.utils.database import get_session


class AuthFilter(SimpleCustomFilter):
    key = "auth"

    async def check(self, event: Message | CallbackQuery):
        if type(event) is Message:
            if event.text.startswith("/start"):
                return True
        user_id = event.from_user.id
        with get_session() as session:
            auth = get_user_telegram_api_key_by_tg_user_id(user_id, session)
            if auth is not None:
                return True
        return False
