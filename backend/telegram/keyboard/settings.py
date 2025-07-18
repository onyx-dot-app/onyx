from typing import Sequence

from telebot import types

from onyx.db.models import Persona, LLMProvider


def settings_constructor_for_personas(personas: Sequence[Persona]) -> types.InlineKeyboardMarkup:
    keyboard = types.InlineKeyboardMarkup()
    for persona in personas:
        button = types.InlineKeyboardButton(text=persona.name, callback_data=f"persona_{persona.id}_{persona.prompts[0].id}")
        keyboard.add(button)

    return keyboard


def settings_constructor_for_llm_providers(llm_providers: Sequence[LLMProvider]) -> types.InlineKeyboardMarkup:
    keyboard = types.InlineKeyboardMarkup()
    for provider in llm_providers:
        button = types.InlineKeyboardButton(text=provider.provider, callback_data=f"model_{provider.name}_{provider.default_model_name}")
        keyboard.add(button)

    return keyboard
