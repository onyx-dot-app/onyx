"""Builders for the Zoom response models the connector tests need.

The models require every field Zoom documents as always-present, but a test
only ever cares about one or two of them. Build from these defaults and pass
the field under test as an override.
"""

from typing import Any

from onyx.connectors.zoom.models import (
    ZoomSessionDetails,
    ZoomSessionOccurrence,
    ZoomTranscript,
)


def transcript(**overrides: Any) -> ZoomTranscript:
    fields: dict[str, Any] = {
        "meeting_id": "uaFkQyFCSwya8iNYtkAw3A==",
        "account_id": "Cx3wERazSgup7ZWRHQM8-w",
        "meeting_topic": "My Personal Meeting",
        "host_id": "_0ctZtY0REqWalTmwvrdIw",
        "transcript_created_time": "2025-06-27T13:48:24Z",
        "can_download": True,
    }
    return ZoomTranscript(**(fields | overrides))


def session_details(**overrides: Any) -> ZoomSessionDetails:
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
    return ZoomSessionDetails(**(fields | overrides))


def occurrence(**overrides: Any) -> ZoomSessionOccurrence:
    fields: dict[str, Any] = {
        "uuid": "uuid-1",
        "start_time": "2026-01-15T10:00:00Z",
    }
    return ZoomSessionOccurrence(**(fields | overrides))
