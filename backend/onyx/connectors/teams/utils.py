import time
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from http import HTTPStatus

from office365.graph_client import GraphClient  # type: ignore
from pydantic import Json

from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.teams.models import Message


def retry(
    graph_client: GraphClient,
    request_url: str,
) -> Json:
    MAX_RETRIES = 10
    retry_number = 0

    while retry_number < MAX_RETRIES:
        response = graph_client.execute_request_direct(request_url)
        if response.ok:
            return response.json()

        if response.status_code == int(HTTPStatus.TOO_MANY_REQUESTS):
            retry_number += 1

            cooldown = int(response.headers.get("Retry-After", 10))
            time.sleep(cooldown)

            continue

        response.raise_for_status()

    raise RuntimeError(
        f"Max number of retries for hitting {request_url=} exceeded; unable to fetch data"
    )


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

    json_response = retry(graph_client=graph_client, request_url=request_url)

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

    response_json = retry(graph_client=graph_client, request_url=request_url)

    for value in response_json.get("value", []):
        yield Message(**value)
