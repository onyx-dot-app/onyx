from telebot import State
from telebot.states import StatesGroup


class ChatStates(StatesGroup):
    MAIN = State()

