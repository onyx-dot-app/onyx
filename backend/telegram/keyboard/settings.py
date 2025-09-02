from enum import Enum
from typing import Sequence

from telebot import types
from telebot.types import ReplyKeyboardMarkup, KeyboardButton

from onyx.db.models import Persona, LLMProvider


class MENU_BUTTONS_TXT(Enum):
    edit_model = "Выбор модели"
    restart = "Рестарт"
    edit_persona = "Выбор ассистента"


def settings_constructor_for_personas(personas: Sequence[Persona]) -> types.InlineKeyboardMarkup:
    keyboard = types.InlineKeyboardMarkup()
    for persona in personas:
        button = types.InlineKeyboardButton(text=persona.name, callback_data=f"persona_{persona.id}_{persona.prompts[0].id}")
        keyboard.add(button)

    return keyboard


def settings_constructor_for_llm_providers(llm_providers: Sequence[LLMProvider]) -> types.InlineKeyboardMarkup:
    keyboard = types.InlineKeyboardMarkup()
    for provider in llm_providers:
        for model_name in provider.display_model_names:
            button = types.InlineKeyboardButton(text=model_name, callback_data=f"model_{provider.name}_{model_name}")
            keyboard.add(button)

    return keyboard


def create_main_menu_keyboard() -> ReplyKeyboardMarkup:
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    assistant_btn = KeyboardButton(MENU_BUTTONS_TXT.edit_persona.value)
    model_btn = KeyboardButton(MENU_BUTTONS_TXT.edit_model.value)
    restart_btn = KeyboardButton(MENU_BUTTONS_TXT.restart.value)

    keyboard.add(assistant_btn, model_btn, restart_btn)
    return keyboard
