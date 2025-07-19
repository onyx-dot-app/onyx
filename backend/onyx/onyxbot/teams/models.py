from typing import Literal

from pydantic import BaseModel

from onyx.chat.models import ThreadMessage


class TeamsMessageInfo(BaseModel):
    thread_messages: list[ThreadMessage]
    channel_to_respond: str
    msg_to_respond: str | None
    thread_to_respond: str | None
    sender_id: str | None
    email: str | None
    bypass_filters: bool  # User has mentioned the bot
    is_bot_msg: bool  # User is using a bot command
    is_bot_dm: bool  # User is direct messaging to the bot


# Models used to encode the relevant data for the ephemeral message actions
class ActionValuesEphemeralMessageMessageInfo(BaseModel):
    bypass_filters: bool | None
    channel_to_respond: str | None
    msg_to_respond: str | None
    email: str | None
    sender_id: str | None
    thread_messages: list[ThreadMessage] | None
    is_bot_msg: bool | None
    is_bot_dm: bool | None
    thread_to_respond: str | None 