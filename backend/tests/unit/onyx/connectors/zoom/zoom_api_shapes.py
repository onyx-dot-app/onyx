"""Builders for the Zoom response models the connector tests need.

The models require every field Zoom documents as always-present, but a test
only ever cares about one or two of them. Build from these defaults and pass
the field under test as an override.
"""

from typing import Any

from onyx.connectors.zoom.models import (
    ZoomInvitee,
    ZoomPanelist,
    ZoomParticipant,
    ZoomPastMeetingDetails,
    ZoomRecordingEntry,
    ZoomRecordingFile,
    ZoomRegistrant,
    ZoomSessionOccurrence,
    ZoomTranscript,
    ZoomUser,
    ZoomWebinarDetails,
)


def transcript(**overrides: Any) -> ZoomTranscript:
    """Zoom never sends this shape. `recording_file` below is the payload it
    really answers with.
    """
    fields: dict[str, Any] = {"download_url": "https://zoom.example/transcript.vtt"}
    return ZoomTranscript(**(fields | overrides))


def recording_file(**overrides: Any) -> ZoomRecordingFile:
    fields: dict[str, Any] = {
        "meeting_id": "uaFkQyFCSwya8iNYtkAw3A==",
        "recording_start": "2021-03-18T05:41:36Z",
        "file_type": "TRANSCRIPT",
        "id": "ffc44b9b-c1a2-4a9d-9c0a-1b0a01b8ff9d",
        "file_extension": "VTT",
        "file_size": 3260,
        "recording_end": "2021-03-18T06:01:36Z",
        "recording_type": "audio_transcript",
        "status": "completed",
        "download_url": "https://zoom.example/transcript.vtt",
    }
    return ZoomRecordingFile(**(fields | overrides))


def past_meeting_details(**overrides: Any) -> ZoomPastMeetingDetails:
    fields: dict[str, Any] = {
        "uuid": "uaFkQyFCSwya8iNYtkAw3A==",
        "id": 111,
        "topic": "Weekly Sync",
        "start_time": "2026-01-15T10:00:00Z",
        "end_time": "2026-01-15T11:00:00Z",
        "duration": 60,
        "host_id": "_0ctZtY0REqWalTmwvrdIw",
        "dept": "Engineering",
        "participants_count": 4,
        "total_minutes": 240,
        "has_meeting_summary": False,
        "source": "Zoom",
        "type": 2,
        "user_email": "host@example.com",
        "user_name": "Host User",
    }
    return ZoomPastMeetingDetails(**(fields | overrides))


def occurrence(**overrides: Any) -> ZoomSessionOccurrence:
    fields: dict[str, Any] = {
        "uuid": "uuid-1",
        "start_time": "2026-01-15T10:00:00Z",
    }
    return ZoomSessionOccurrence(**(fields | overrides))


def webinar_details(**overrides: Any) -> ZoomWebinarDetails:
    fields: dict[str, Any] = {
        "id": 97871060099,
        "uuid": "m3WqMkvuRXyYqH+eKWhk9w==",
        "host_id": "30R7kT7bTIKSNUFEuH_Qlg",
        "type": 5,
        "topic": "Product Launch",
        "start_time": "2026-01-15T10:00:00Z",
    }
    return ZoomWebinarDetails(**(fields | overrides))


def recording_entry(**overrides: Any) -> ZoomRecordingEntry:
    fields: dict[str, Any] = {
        "uuid": "BOKXuumlTAGXfg==",
        "id": 6840331990,
        "topic": "My Personal Meeting",
        "start_time": "2021-03-18T05:41:36Z",
        "type": "2",
        "account_id": "Cx3wERazSgup7ZWRHQM8-w",
        "host_id": "_0ctZtY0REqWalTmwvrdIw",
        "duration": 20,
        "total_size": 22,
        "recording_count": 22,
    }
    return ZoomRecordingEntry(**(fields | overrides))


def user(**overrides: Any) -> ZoomUser:
    fields: dict[str, Any] = {
        "email": "host@example.com",
        "type": 2,
        "first_name": "Jill",
        "last_name": "Chill",
        "id": "_0ctZtY0REqWalTmwvrdIw",
    }
    return ZoomUser(**(fields | overrides))


def participant(**overrides: Any) -> ZoomParticipant:
    fields: dict[str, Any] = {
        "id": "30R7kT7bTIKSNUFEuH_Qlg",
        "name": "Jill Chill",
        "user_id": "27423744",
        "user_email": "jchill@example.com",
        "join_time": "2022-03-23T06:58:09Z",
        "leave_time": "2022-03-23T07:02:28Z",
        "duration": 259,
        "failover": False,
        "status": "in_meeting",
    }
    return ZoomParticipant(**(fields | overrides))


def registrant(**overrides: Any) -> ZoomRegistrant:
    fields: dict[str, Any] = {
        "email": "jchill@example.com",
        "first_name": "Jill",
    }
    return ZoomRegistrant(**(fields | overrides))


def invitee(**overrides: Any) -> ZoomInvitee:
    fields: dict[str, Any] = {"email": "jchill@example.com"}
    return ZoomInvitee(**(fields | overrides))


def panelist(**overrides: Any) -> ZoomPanelist:
    fields: dict[str, Any] = {
        "id": "Tg2b6GhcQKKbV7nSCbDKug",
        "email": "jchill@example.com",
        "name": "Jill Chill",
        "join_url": "https://example.com/j/11111",
    }
    return ZoomPanelist(**(fields | overrides))
