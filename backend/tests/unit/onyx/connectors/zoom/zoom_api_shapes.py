"""Builders for the Zoom response models the connector tests need.

The models require every field Zoom documents as always-present, but a test
only ever cares about one or two of them. Build from these defaults and pass
the field under test as an override.
"""

from typing import Any

from onyx.connectors.zoom.models import (
    ZoomMeetingDetails,
    ZoomPastMeetingDetails,
    ZoomRecordingAuthenticationRule,
    ZoomRecordingAuthenticationSettings,
    ZoomRecordingEntry,
    ZoomRecordingFile,
    ZoomRecordingRegistrant,
    ZoomRecordingSettings,
    ZoomSessionOccurrence,
    ZoomUser,
    ZoomWebinarDetails,
)


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


def recording_with_transcript(
    download_url: str | None = "https://zoom.example/transcript.vtt",
    is_ready: bool = True,
    meeting_topic: str = "",
    **overrides: Any,
) -> ZoomRecordingEntry:
    """What Zoom answers for a session that has a transcript. The topic defaults
    to empty so callers that care about the details fallback do not have to opt
    out of one."""
    return recording_entry(
        topic=meeting_topic,
        recording_files=[
            recording_file(
                download_url=download_url,
                status="completed" if is_ready else "processing",
            )
        ],
        **overrides,
    )


def meeting_details(**overrides: Any) -> ZoomMeetingDetails:
    fields: dict[str, Any] = {"host_id": "_0ctZtY0REqWalTmwvrdIw"}
    return ZoomMeetingDetails(**(fields | overrides))


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


# The built-in "Signed-in users in my account" rule of the test account.
ACCOUNT_RULE_ID = "internally_GB7nutLVSz-Aoi3nrsxZrw"


def recording_settings(**overrides: Any) -> ZoomRecordingSettings:
    """What Zoom answered for a live recording on "Anyone in Signed-in users in
    my account"."""
    fields: dict[str, Any] = {
        "share_recording": "publicly",
        "recording_authentication": True,
        "authentication_option": ACCOUNT_RULE_ID,
        "authentication_name": "Signed-in users in my account",
        "on_demand": False,
    }
    return ZoomRecordingSettings(**(fields | overrides))


def recording_registrant(**overrides: Any) -> ZoomRecordingRegistrant:
    fields: dict[str, Any] = {"email": "jchill@example.com", "status": "approved"}
    return ZoomRecordingRegistrant(**(fields | overrides))


def recording_authentication_rule(**overrides: Any) -> ZoomRecordingAuthenticationRule:
    fields: dict[str, Any] = {
        "id": ACCOUNT_RULE_ID,
        "type": "internally",
        "name": "Signed-in users in my account",
    }
    return ZoomRecordingAuthenticationRule(**(fields | overrides))


def domain_rule(
    domains: str = "example.com", **overrides: Any
) -> ZoomRecordingAuthenticationRule:
    fields: dict[str, Any] = {
        "id": "KtK6lLjFQp24UqYxdYQQuA",
        "type": "enforce_login_with_domains",
        "name": "testing access with specified domains",
        "domains": domains,
    }
    return ZoomRecordingAuthenticationRule(**(fields | overrides))


def recording_authentication_settings(
    *rules: ZoomRecordingAuthenticationRule,
) -> ZoomRecordingAuthenticationSettings:
    return ZoomRecordingAuthenticationSettings(
        recording_authentication=True,
        authentication_options=list(rules or [recording_authentication_rule()]),
    )
