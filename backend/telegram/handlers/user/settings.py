from sqlalchemy.orm import Session
from telebot.async_telebot import AsyncTeleBot
from telebot.states.asyncio import StateContext
from telebot.types import Message, CallbackQuery

from onyx.db.llm import fetch_existing_llm_providers_for_user
from onyx.db.persona import get_personas_for_user
from onyx.db.telegram import get_user_by_telegram_user_id, \
    edit_user_telegram_settings_persona, edit_user_telegram_settings_model
from telegram.keyboard.settings import settings_constructor_for_personas, settings_constructor_for_llm_providers
from telegram.utils.database import with_session


def handler(bot: AsyncTeleBot):
    @bot.message_handler(commands=["model"], auth=True)
    @with_session
    async def handle_edit_model(message: Message, session: Session, state: StateContext):
        user_by_token = get_user_by_telegram_user_id(message.from_user.id, session)

        llm_providers = fetch_existing_llm_providers_for_user(session, user_by_token)

        keyboard = settings_constructor_for_llm_providers(llm_providers)

        await bot.send_message(chat_id=message.from_user.id, text="Выберите Модель: ", reply_markup=keyboard)

    @bot.message_handler(commands=["assistant"], auth=True)
    @with_session
    async def handle_edit_persona(message: Message, session: Session, state: StateContext):
        user_by_token = get_user_by_telegram_user_id(message.from_user.id, session)

        personas = get_personas_for_user(user_by_token, session, get_editable=False)

        keyboard = settings_constructor_for_personas(personas)

        await bot.send_message(chat_id=message.from_user.id, text="Выберите Ассистента: ", reply_markup=keyboard)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("persona_"), auth=True)
    @with_session
    async def change_persona(call: CallbackQuery, session: Session, state: StateContext):
        persona_id = int(call.data.split("_")[1])
        prompt_id = int(call.data.split("_")[2])

        edit_user_telegram_settings_persona(call.from_user.id, persona_id, prompt_id, session)

        await bot.send_message(call.from_user.id, "Вы успешно сменили ассистента!")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("model_"), auth=True)
    @with_session
    async def change_model(call: CallbackQuery, session: Session, state: StateContext):
        model = {
            "model_provider": call.data.split("_")[1],
            "model_version": call.data.split("_")[2]
        }

        edit_user_telegram_settings_model(call.from_user.id, model, session)

        await bot.send_message(call.from_user.id, "Вы успешно сменили модель!")

