from pydantic import BaseModel

from onyx.chat.models import ThreadMessage


class SlackMessageInfo(BaseModel):
    thread_messages: list[ThreadMessage]
    channel_to_respond: str
    msg_to_respond: str | None
    thread_to_respond: str | None
    sender_id: str | None
    email: str | None
    bypass_filters: bool  # User has tagged @OnyxBot
    is_bot_msg: bool  # User is using /OnyxBot
    is_bot_dm: bool  # User is direct messaging to OnyxBot
