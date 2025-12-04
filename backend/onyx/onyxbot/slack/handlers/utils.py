from slack_sdk import WebClient

from onyx.onyxbot.slack.utils import respond_in_thread_or_channel


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
