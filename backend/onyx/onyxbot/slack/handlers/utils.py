from slack_sdk import WebClient

from onyx.chat.models import ThreadMessage
from onyx.configs.constants import MessageType
from onyx.onyxbot.slack.utils import respond_in_thread_or_channel


def slackify_message_thread(messages: list[ThreadMessage]) -> str:
    # Note: this does not handle extremely long threads, every message will be included
    # with weaker LLMs, this could cause issues with exceeeding the token limit
    if not messages:
        return ""

    message_strs: list[str] = []
    for message in messages:
        if message.role == MessageType.USER:
            message_text = (
                f"{message.sender or 'Unknown User'} said in Slack:\n{message.message}"
            )
        elif message.role == MessageType.ASSISTANT:
            message_text = f"AI said in Slack:\n{message.message}"
        else:
            message_text = (
                f"{message.role.value.upper()} said in Slack:\n{message.message}"
            )
        message_strs.append(message_text)

    return "\n\n".join(message_strs)


def send_team_member_message(
    client: WebClient,
    channel: str,
    thread_ts: str,
    receiver_ids: list[str] | None = None,
    send_as_ephemeral: bool = False,
) -> None:
    respond_in_thread_or_channel(
        client=client,
        channel=channel,
        text=(
            "👋 Hi, we've just gathered and forwarded the relevant "
            + "information to the team. They'll get back to you shortly!"
        ),
        thread_ts=thread_ts,
        receiver_ids=None,
        send_as_ephemeral=send_as_ephemeral,
    )
