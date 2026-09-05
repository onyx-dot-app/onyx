from pydantic import BaseModel


class ZoomTranscript(BaseModel):
    """Response shape of `GET /meetings/{meetingId}/transcript`."""

    meeting_id: str | None = None
    meeting_topic: str | None = None
    host_id: str | None = None
    can_download: bool | None = None
    download_url: str | None = None
    download_restriction_reason: str | None = None
    transcript_created_time: str | None = None
    auto_delete: bool | None = None
    auto_delete_date: str | None = None

    @property
    def is_downloadable(self) -> bool:
        """Zoom documents these three fields as mutually exclusive, then their
        own example returns all three together, so no one of them can be trusted.
        """
        return (
            self.can_download is not False
            and self.download_restriction_reason is None
            and bool(self.download_url)
        )


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
