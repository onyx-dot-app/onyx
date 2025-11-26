from sqlalchemy.orm import Session
from telebot.async_telebot import AsyncTeleBot
from telebot.states.asyncio import StateContext
from telebot.types import Message, CallbackQuery

from onyx.db.llm import fetch_existing_llm_providers_for_user
from onyx.db.persona import get_personas_for_user
from onyx.db.telegram import get_user_by_telegram_user_id, \
    edit_user_telegram_settings_persona, edit_user_telegram_settings_model, get_user_telegram_settings
from onyx.utils.logger import setup_logger
from telegram.keyboard.settings import MENU_BUTTONS_TXT, settings_constructor_for_personas, settings_constructor_for_llm_providers
from telegram.utils.database import with_session

logger = setup_logger()


def handler(bot: AsyncTeleBot):
    @bot.message_handler(
        func=lambda msg: msg.text in ["/model", MENU_BUTTONS_TXT.edit_model.value],
        auth=True
    )
    @with_session
    async def handle_edit_model(message: Message, session: Session, state: StateContext):
        user_by_token = get_user_by_telegram_user_id(message.from_user.id, session)

        llm_providers = fetch_existing_llm_providers_for_user(session, user_by_token)
        
        # Получаем текущие настройки пользователя
        user_settings = get_user_telegram_settings(message.from_user.id, session)
        current_model = user_settings.model if user_settings else None
        
        keyboard = settings_constructor_for_llm_providers(llm_providers, current_model=current_model)
        
        # Формируем сообщение с текущей моделью
        if current_model:
            current_model_text = f"{current_model.get('model_version', 'N/A')}"
            message_text = f"Выберите LLM-модель\n\nТекущая LLM-модель: {current_model_text}"
        else:
            message_text = "Выберите LLM-модель"

        await bot.send_message(chat_id=message.from_user.id, text=message_text, reply_markup=keyboard)

    @bot.message_handler(
        func=lambda msg: msg.text in ["/assistant", MENU_BUTTONS_TXT.edit_persona.value],
        auth=True
    )
    @with_session
    async def handle_edit_persona(message: Message, session: Session, state: StateContext):
        user_by_token = get_user_by_telegram_user_id(message.from_user.id, session)

        personas = get_personas_for_user(user_by_token, session, get_editable=False)
        
        # Получаем текущие настройки пользователя
        user_settings = get_user_telegram_settings(message.from_user.id, session)
        current_persona_id = user_settings.persona_id if user_settings else None
        
        keyboard = settings_constructor_for_personas(personas, current_persona_id=current_persona_id)

        msg = "Выберите ассистента"
        await bot.send_message(chat_id=message.from_user.id, text=msg, reply_markup=keyboard)

    @bot.callback_query_handler(
        func=lambda call: call.data.startswith("persona_"),
        auth=True
    )
    @with_session
    async def change_persona(call: CallbackQuery, session: Session, state: StateContext):
        persona_id = int(call.data.split("_")[1])
        prompt_id = int(call.data.split("_")[2])

        edit_user_telegram_settings_persona(call.from_user.id, persona_id, prompt_id, session)

        # Редактируем существующее сообщение с новой клавиатурой
        try:
            user_by_token = get_user_by_telegram_user_id(call.from_user.id, session)
            personas = get_personas_for_user(user_by_token, session, get_editable=False)
            keyboard = settings_constructor_for_personas(personas, current_persona_id=persona_id)

            await bot.edit_message_reply_markup(
                chat_id=call.from_user.id,
                message_id=call.message.message_id,
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error("Ошибка при редактировании клавиатуры со списком ассистентов: %s", str(e))

        # Очищаем состояние чата, чтобы следующее сообщение создало новую сессию
        await state.delete()
        await bot.answer_callback_query(call.id)

        msg = f"Вы успешно переключились на другого ассистента!"
        await bot.send_message(call.from_user.id, msg)

    @bot.callback_query_handler(
        func=lambda call: call.data.startswith("model_"),
        auth=True
    )
    @with_session
    async def change_model(call: CallbackQuery, session: Session, state: StateContext):
        model = {
            "model_provider": call.data.split("_")[1],
            "model_version": call.data.split("_")[2]
        }

        edit_user_telegram_settings_model(call.from_user.id, model, session)

        # Редактируем существующее сообщение с новой клавиатурой
        try:
            user_by_token = get_user_by_telegram_user_id(call.from_user.id, session)
            llm_providers = fetch_existing_llm_providers_for_user(session, user_by_token)
            keyboard = settings_constructor_for_llm_providers(llm_providers, current_model=model)

            await bot.edit_message_reply_markup(
                chat_id=call.from_user.id,
                message_id=call.message.message_id,
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error("Ошибка при редактировании клавиатуры со списком LLM-моделей: %s", str(e))

        await bot.answer_callback_query(call.id)
        msg = f"Вы успешно сменили LLM-модель!\n\nТекущая LLM-модель: {model['model_version']}"
        await bot.send_message(call.from_user.id, msg)
