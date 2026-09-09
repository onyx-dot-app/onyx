"""Response models for the Zoom endpoints this connector calls.

These mirror Zoom's documented responses and nothing else. A field is `| None`
only where Zoom types it `string | null`, and it has a default only where
Zoom's own text says the field is conditional.
"""

from pydantic import BaseModel


class ZoomTranscript(BaseModel):
    """Response shape of `GET /meetings/{meetingId}/transcript`."""

    meeting_id: str
    account_id: str
    meeting_topic: str
    host_id: str
    can_download: bool
    transcript_created_time: str

    auto_delete: bool | None = None
    auto_delete_date: str | None = None
    download_url: str | None = None
    download_restriction_reason: str | None = None

    @property
    def is_downloadable(self) -> bool:
        """Zoom documents these three fields as mutually exclusive, then returns
        all three together in its own example, so all three must agree here.
        """
        return (
            self.can_download
            and self.download_restriction_reason is None
            and bool(self.download_url)
        )


class ZoomPastMeetingDetails(BaseModel):
    """Response shape of `GET /past_meetings/{meetingId}`."""

    uuid: str
    id: int
    topic: str
    start_time: str
    end_time: str
    duration: int
    host_id: str
    dept: str
    participants_count: int
    total_minutes: int
    has_meeting_summary: bool
    source: str
    type: int
    user_email: str
    user_name: str


class ZoomMeetingOccurrence(BaseModel):
    """One entry from `GET /past_meetings/{meetingId}/instances`."""

    uuid: str
    start_time: str
