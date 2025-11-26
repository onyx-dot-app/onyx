from enum import Enum
from typing import Sequence

from telebot import types
from telebot.types import ReplyKeyboardMarkup, KeyboardButton

from onyx.db.models import Persona, LLMProvider


class MENU_BUTTONS_TXT(Enum):
    edit_model = "Выбор модели"
    restart = "Рестарт"
    edit_persona = "Выбор ассистента"


def settings_constructor_for_personas(
    personas: Sequence[Persona],
    current_persona_id: int | None = None
) -> types.InlineKeyboardMarkup:
    keyboard = types.InlineKeyboardMarkup()
    for persona in personas:
        # Помечаем текущий выбранный ассистент галочкой
        is_current = current_persona_id is not None and persona.id == current_persona_id
        button_text = f"✔️ {persona.name}" if is_current else persona.name
        
        button = types.InlineKeyboardButton(
            text=button_text,
            callback_data=f"persona_{persona.id}_{persona.prompts[0].id}",
        )
        keyboard.add(button)

    return keyboard


def settings_constructor_for_llm_providers(
    llm_providers: Sequence[LLMProvider],
    current_model: dict | None = None
) -> types.InlineKeyboardMarkup:
    keyboard = types.InlineKeyboardMarkup()
    for provider in llm_providers:
        for model_name in provider.display_model_names:
            # Помечаем текущую выбранную модель галочкой
            is_current = (
                current_model is not None
                and current_model.get("model_provider") == provider.name
                and current_model.get("model_version") == model_name
            )
            button_text = f"✔️ {model_name}" if is_current else model_name
            
            button = types.InlineKeyboardButton(
                text=button_text,
                callback_data=f"model_{provider.name}_{model_name}"
            )
            keyboard.add(button)

    return keyboard


def create_main_menu_keyboard() -> ReplyKeyboardMarkup:
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    assistant_btn = KeyboardButton(MENU_BUTTONS_TXT.edit_persona.value)
    model_btn = KeyboardButton(MENU_BUTTONS_TXT.edit_model.value)
    restart_btn = KeyboardButton(MENU_BUTTONS_TXT.restart.value)

    keyboard.add(assistant_btn, model_btn, restart_btn)
    return keyboard
