from pydantic import BaseModel


class ZoomTranscript(BaseModel):
    """Response shape of `GET /meetings/{meetingId}/transcript`."""

    download_url: str | None = None
    download_restriction_reason: str | None = None
    transcript_created_time: str | None = None
    auto_delete: bool | None = None
    auto_delete_date: str | None = None


class ZoomPastMeetingDetails(BaseModel):
    """Response shape of `GET /past_meetings/{meetingId}`."""

    uuid: str | None = None
    topic: str | None = None
    start_time: str | None = None
    duration: int | None = None


class ZoomMeetingOccurrence(BaseModel):
    """One entry from `GET /past_meetings/{meetingId}/instances`."""

    uuid: str
    start_time: str | None = None
