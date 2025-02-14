from pydantic import BaseModel

from onyx.chat.models import ThreadMessage


class DiscordMessageInfo(BaseModel):
    thread_messages: list[ThreadMessage]
    channel_to_respond: str
    msg_to_respond: str | None
    thread_to_respond: str | None
    sender_id: str | None
    email: str | None
    tenant_id: str | None
    bypass_filters: bool
    is_bot_msg: bool
    is_bot_dm: bool
