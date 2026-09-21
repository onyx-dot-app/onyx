"""Graph doubles and a checkpoint stepper shared by the Teams unit tests.

Lives beside the tests rather than in conftest.py because pytest imports
conftest itself and test modules are not meant to import it back."""

from typing import Any
from unittest.mock import MagicMock

import requests

from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.microsoft_utils.graph_auth import MicrosoftAuthMethod
from onyx.connectors.models import ConnectorFailure, Document
from onyx.connectors.teams.connector import TeamsCheckpoint, TeamsConnector
from onyx.connectors.teams.models import ChannelRef
from onyx.connectors.teams.utils import message_delta_url

TEAM_ID = "team-1"
CHANNEL_ID = "19:channel@thread.tacv2"
SERVICE_ROOT = "https://graph.microsoft.com/v1.0"
MEMBERS_URL = f"teams/{TEAM_ID}/channels/{CHANNEL_ID}/allMembers"
DELTA_URL = message_delta_url(TEAM_ID, CHANNEL_ID, 0)
CHANNEL = ChannelRef(team_id=TEAM_ID, id=CHANNEL_ID, display_name="General")


def replies_url(root_id: str, channel_id: str = CHANNEL_ID) -> str:
    return f"teams/{TEAM_ID}/channels/{channel_id}/messages/{root_id}/replies"


def response(status: int, payload: dict[str, Any]) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.ok = status < 400
    resp.status_code = status
    resp.headers = {}
    resp.json.return_value = payload
    if status >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(
            f"{status}", response=resp
        )
    return resp


def graph_client(
    routes: dict[str, dict[str, Any]], refused: dict[str, int] | None = None
) -> MagicMock:
    """A client whose direct requests answer from ``routes``, fail with the
    status in ``refused``, and 404 elsewhere. The SDK raises on every non-2xx
    status, so failures arrive as exceptions the way they do in production."""
    client = MagicMock()
    client.service_root_url.return_value = SERVICE_ROOT

    def execute(url: str) -> MagicMock:
        if url in routes:
            return response(200, routes[url])
        status = (refused or {}).get(url, 404)
        resp = response(status, {"error": {"code": str(status)}})
        raise requests.HTTPError(str(status), response=resp)

    client.execute_request_direct.side_effect = execute
    return client


def member(name: str | None, email: str | None, user_id: str) -> dict[str, Any]:
    return {"displayName": name, "email": email, "userId": user_id}


def message(
    message_id: str,
    text: str | None,
    reply_to: str | None = None,
    created: str = "2026-09-01T10:00:00Z",
    modified: str | None = None,
    deleted: str | None = None,
    message_type: str = "message",
    sender: str | None = "Ada",
) -> dict[str, Any]:
    return {
        "id": message_id,
        "replyToId": reply_to,
        "subject": None if reply_to else f"Subject {message_id}",
        "from": {"user": {"id": "u1", "displayName": sender}} if sender else None,
        "messageType": message_type,
        "body": {
            "contentType": "html",
            "content": f"<p>{text}</p>" if text is not None else None,
        },
        "createdDateTime": created,
        "lastModifiedDateTime": modified or created,
        "lastEditedDateTime": None,
        "deletedDateTime": deleted,
        "webUrl": f"https://teams.example/{message_id}",
    }


def connector(
    client: MagicMock,
    include_attachments: bool = False,
    include_inline_images: bool = False,
) -> TeamsConnector:
    teams_connector = TeamsConnector(
        include_attachments=include_attachments,
        include_inline_images=include_inline_images,
    )
    teams_connector.graph_client = client
    # The factory grants this from the image analysis setting.
    teams_connector.set_allow_images(True)
    teams_connector.msal_app = MagicMock()
    teams_connector._acquire_token = lambda: {"access_token": "token"}
    teams_connector._auth_method = (
        MicrosoftAuthMethod.CERTIFICATE
        if include_attachments
        else MicrosoftAuthMethod.CLIENT_SECRET
    )
    return teams_connector


def channel_checkpoint(channel: ChannelRef = CHANNEL) -> TeamsCheckpoint:
    """A checkpoint about to walk ``channel``'s first page, nothing after it."""
    return TeamsCheckpoint(has_more=True, todo_team_ids=[], current_channel=channel)


def step(
    teams_connector: TeamsConnector,
    checkpoint: TeamsCheckpoint,
    start: SecondsSinceUnixEpoch = 0,
) -> tuple[list[Document | ConnectorFailure], TeamsCheckpoint]:
    """One connector step, with the checkpoint round-tripped through JSON the
    way the indexing pipeline persists it."""
    items: list[Document | ConnectorFailure] = []
    generator = teams_connector.load_from_checkpoint(start, start + 1, checkpoint)
    while True:
        try:
            item = next(generator)
        except StopIteration as stop:
            next_checkpoint = teams_connector.validate_checkpoint_json(
                stop.value.model_dump_json()
            )
            return items, next_checkpoint
        assert isinstance(item, (Document, ConnectorFailure))
        items.append(item)


def walk_channel(
    teams_connector: TeamsConnector, channel: ChannelRef = CHANNEL
) -> list[Document | ConnectorFailure]:
    """Every item of one channel, page by page."""
    checkpoint = channel_checkpoint(channel)
    items: list[Document | ConnectorFailure] = []
    while checkpoint.has_more:
        page_items, checkpoint = step(teams_connector, checkpoint)
        items.extend(page_items)
    return items
