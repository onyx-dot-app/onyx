from io import BytesIO

from sqlalchemy.orm import Session
from telebot.async_telebot import AsyncTeleBot
from telebot.states.asyncio import StateContext
from telebot.types import Message

from onyx.db.telegram import get_user_telegram_settings, get_user_telegram_api_key_by_tg_user_id
from telegram.states.chat import ChatStates
from telegram.utils.database import with_session
from telegram.utils.telegram import request_answer_from_smartsearch


def handler(bot: AsyncTeleBot):
    @bot.message_handler(state=ChatStates.MAIN, commands=['restart'], auth=True)
    async def handle_restart(message: Message, state: StateContext):
        await state.delete()
        await bot.send_message(message.from_user.id,
                               "Новый чат успешно начат!\n\nВведите /menu для просмотра списка команд.")

    @bot.message_handler(state=ChatStates.MAIN, auth=True, content_types=['text', 'document'])
    @with_session
    async def handel_messages(message: Message, session: Session, state: StateContext):
        if message.document:
            file = await bot.get_file(message.document.file_id)
            file_bytes = await bot.download_file(file.file_path)
            file_stream = BytesIO(file_bytes)
            text = message.caption
            files = (message.document.file_name, file_stream, message.document.mime_type)
        else:
            text = message.text
            files = None
        user_settings = get_user_telegram_settings(message.from_user.id, session)
        user_token = get_user_telegram_api_key_by_tg_user_id(message.from_user.id, session)
        async with state.data() as data:
            chat_session_id = data.get("chat_session_id")
            parent_message_id = data.get("parent_message_id")
        answer = request_answer_from_smartsearch(
            message=text,
            token=user_token.api_key,
            chat_session_id=chat_session_id,
            persona_id=user_settings.persona_id if user_settings.persona_id is not None else 1,
            llm_model=user_settings.model or None,
            parent_message_id=parent_message_id,
            files=files
        )

        await bot.send_message(message.from_user.id, answer['message'])
        await state.add_data(parent_message_id=answer['parent_message_id'])

    @bot.message_handler(auth=True, content_types=['document', 'text'])
    @with_session
    async def handle_first_message_after_restart(message: Message, session: Session, state: StateContext):
        if message.document:
            file = await bot.get_file(message.document.file_id)
            file_bytes = await bot.download_file(file.file_path)
            file_stream = BytesIO(file_bytes)
            text = message.caption
            files = (message.document.file_name, file_stream, message.document.mime_type)
        else:
            text = message.text
            files = None
        user_settings = get_user_telegram_settings(message.from_user.id, session)
        user_token = get_user_telegram_api_key_by_tg_user_id(message.from_user.id, session)
        answer = request_answer_from_smartsearch(
            message=text,
            token=user_token.api_key,
            persona_id=user_settings.persona_id if user_settings.persona_id is not None else 0,
            llm_model=user_settings.model or None,
            files=files
        )

        await bot.send_message(message.from_user.id, answer['message'])

        await state.set(ChatStates.MAIN)
        await state.add_data(chat_session_id=answer['chat_session_id'], parent_message_id=answer['parent_message_id'])
