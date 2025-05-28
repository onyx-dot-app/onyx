from typing import Literal

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


class ActionValuesEphemeralMessageChannelConfig(BaseModel):
    channel_name: str | None
    respond_tag_only: bool | None
    respond_to_bots: bool | None
    is_ephemeral: bool
    respond_member_group_list: list[str] | None
    answer_filters: (
        list[Literal["well_answered_postfilter", "questionmark_prefilter"]] | None
    )
    follow_up_tags: list[str] | None
    show_continue_in_web_ui: bool


class ActionValuesEphemeralMessage(BaseModel):
    original_question_ts: str | None
    feedback_reminder_id: str | None
    chat_message_id: int
    message_info: ActionValuesEphemeralMessageMessageInfo
    channel_conf: ActionValuesEphemeralMessageChannelConfig
