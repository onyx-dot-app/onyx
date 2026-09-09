"""Shared builders for the Zoom connector unit tests.

Lives beside the tests rather than in conftest.py because pytest imports
conftest itself and test modules are not meant to import it back. This follows
the same shape as tests/unit/onyx/connectors/box/fake_box_client.py.
"""

from unittest.mock import MagicMock

import requests

from onyx.connectors.zoom.client import ZoomClient
from onyx.connectors.zoom.models import (
    ZoomInvitee,
    ZoomPanelist,
    ZoomParticipant,
    ZoomRegistrant,
)
from onyx.connectors.zoom.recordings.models import OccurrenceWork, ZoomSessionType
from tests.unit.onyx.connectors.zoom.zoom_api_shapes import transcript

SAMPLE_VTT = """WEBVTT

1
00:00:00.000 --> 00:00:02.500
Jane Doe: Hello everyone, welcome to the call.

2
00:00:02.600 --> 00:00:05.000
John Smith: Thanks for having me.
"""

TRANSCRIPT_URL = "https://zoom.example/transcript.vtt"


def http_error(status: int, code: int | str | None = None) -> requests.HTTPError:
    """Zoom reports plan and retention problems as its own code in the body of a
    400, so a test that cares which one needs the body as well as the status.
    """
    response = requests.Response()
    response.status_code = status
    if code is not None:
        response._content = f'{{"code": {code!r}, "message": "nope"}}'.replace(
            "'", '"'
        ).encode()
    else:
        response._content = b"not json"
    return requests.HTTPError("boom", response=response)


def occurrence_work(
    session_type: ZoomSessionType = ZoomSessionType.MEETING,
    *,
    session_id: str = "111",
    occurrence_uuid: str = "uuid-abc",
    topic: str | None = None,
    start_time: str | None = "2026-01-15T10:00:00Z",
) -> OccurrenceWork:
    return OccurrenceWork(
        session_type=session_type,
        session_id=session_id,
        occurrence_uuid=occurrence_uuid,
        start_time=start_time,
        topic=topic,
    )


def mock_zoom_client() -> MagicMock:
    return MagicMock(spec=ZoomClient)


def with_transcript(
    client: MagicMock | None = None, vtt: str = SAMPLE_VTT
) -> MagicMock:
    if client is None:
        client = mock_zoom_client()
    # An empty topic makes the caller fall back to the details endpoint, which
    # is what most of these tests are about.
    client.get_meeting_transcript.return_value = transcript(
        download_url=TRANSCRIPT_URL, meeting_topic=""
    )
    client.download_transcript_vtt.return_value = vtt
    return client


def with_access(
    client: MagicMock | None = None,
    participants: list[ZoomParticipant] | None = None,
    registrants: list[ZoomRegistrant] | None = None,
    invitees: list[ZoomInvitee] | None = None,
    panelists: list[ZoomPanelist] | None = None,
) -> MagicMock:
    """Meetings and webinars read the same three kinds of people from different
    endpoints, so each list is answered on both sides.
    """
    if client is None:
        client = mock_zoom_client()
    client.list_past_meeting_participants.return_value = participants or []
    client.list_past_webinar_participants.return_value = participants or []
    client.list_meeting_registrants.return_value = registrants or []
    client.list_webinar_registrants.return_value = registrants or []
    client.list_meeting_invitees.return_value = invitees or []
    client.list_webinar_panelists.return_value = panelists or []
    return client
