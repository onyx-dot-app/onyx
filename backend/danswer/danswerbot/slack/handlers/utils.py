from slack_sdk import WebClient

from danswer.danswerbot.slack.utils import respond_in_thread


def send_team_member_message(
    client: WebClient,
    channel: str,
    thread_ts: str,
) -> None:
    respond_in_thread(
        client=client,
        channel=channel,
        text=(
            "👋 Hi, we've just gathered and forwarded the relevant "
            + "information to the team. They'll get back to you shortly!"
        ),
        thread_ts=thread_ts,
    )
