from collections.abc import Generator
from datetime import datetime
from datetime import timezone

from office365.graph_client import GraphClient  # type: ignore

from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.teams.models import Message


def fetch_messages(
    graph_client: GraphClient,
    team_id: str,
    channel_id: str,
    start: SecondsSinceUnixEpoch,
) -> Generator[Message]:
    startfmt = datetime.fromtimestamp(start, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    request_url = (
        f"teams/{team_id}/channels/{channel_id}/messages/delta"
        f"?$filter=lastModifiedDateTime gt {startfmt}"
    )

    response = graph_client.execute_request_direct(request_url)
    response.raise_for_status()

    json_response = response.json()

    for value in json_response.get("value", []):
        yield Message(**value)


def fetch_replies(
    graph_client: GraphClient,
    team_id: str,
    channel_id: str,
    root_message_id: str,
) -> Generator[Message]:
    request_url = (
        f"teams/{team_id}/channels/{channel_id}" f"/messages/{root_message_id}/replies"
    )

    response = graph_client.execute_request_direct(request_url)
    response.raise_for_status()

    json_response = response.json()

    for value in json_response.get("value", []):
        yield Message(**value)
