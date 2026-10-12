"""Shared builders for the Zoom connector unit tests.

Lives beside the tests rather than in conftest.py because pytest imports
conftest itself and test modules are not meant to import it back. This follows
the same shape as tests/unit/onyx/connectors/box/fake_box_client.py.
"""

from unittest.mock import MagicMock

import requests

from onyx.connectors.zoom.client import ZoomClient
from onyx.connectors.zoom.models import (
    ZoomRecordingAuthenticationRule,
    ZoomRecordingRegistrant,
    ZoomRecordingSettings,
    ZoomUser,
    ZoomUserPage,
)
from onyx.connectors.zoom.recordings.models import OccurrenceWork, ZoomSessionType
from tests.unit.onyx.connectors.zoom.zoom_api_shapes import (
    recording_authentication_settings,
    recording_settings,
    recording_with_transcript,
    user,
)

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
    client: MagicMock | None = None,
    vtt: str = SAMPLE_VTT,
    *,
    host_id: str | None = None,
) -> MagicMock:
    """With a host named, the recording answers with the uuid it was asked for,
    the way Zoom does, so access can be resolved on that answer."""
    if client is None:
        client = mock_zoom_client()
    # No topic makes the caller fall back to the details endpoint, which is
    # what most of these tests are about.
    if host_id is None:
        client.get_recording.return_value = recording_with_transcript(
            download_url=TRANSCRIPT_URL
        )
    else:
        client.get_recording.side_effect = lambda uuid: recording_with_transcript(
            uuid=uuid, host_id=host_id, download_url=TRANSCRIPT_URL
        )
    client.download_transcript_vtt.return_value = vtt
    return client


def with_recording_access(
    client: MagicMock | None = None,
    *,
    settings: ZoomRecordingSettings | None = None,
    owner: ZoomUser | None = None,
    rules: list[ZoomRecordingAuthenticationRule] | None = None,
    registrants: list[ZoomRecordingRegistrant] | None = None,
) -> MagicMock:
    """An account with one owner, the built-in sign-in rule, and a recording
    shared with the account, unless told otherwise. The owner answers for any
    id asked for, since a test names the owner it wants on the recording, and
    is also the one user the account lists."""
    if client is None:
        client = mock_zoom_client()
    client.get_recording_settings.return_value = settings or recording_settings()
    owner = owner or user(id="owner-1", email="Owner@Example.com")
    client.get_user.return_value = owner
    client.list_users.return_value = ZoomUserPage(users=[owner], total_records=1)
    client.get_recording_authentication_rules.return_value = (
        recording_authentication_settings(*(rules or []))
    )
    client.list_recording_registrants.return_value = registrants or []
    return client
