"""Response models for the Zoom endpoints this connector calls.

These mirror Zoom's documented responses and nothing else. A field is `| None`
only where Zoom types it `string | null`, and it has a default only where
Zoom's own text says the field is conditional.
"""

from pydantic import BaseModel, Field


class ZoomAccessToken(BaseModel):
    """Response shape of `POST https://zoom.us/oauth/token`.

    Zoom's API export does not document this endpoint, so these types come from
    Zoom's OAuth docs and not from the export every other model here follows.
    """

    access_token: str
    expires_in: int
    token_type: str | None = None
    scope: str | None = None
    api_url: str | None = None


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


class ZoomSessionDetails(BaseModel):
    """The two fields both details endpoints always carry. Meetings and webinars
    answer with different shapes, so each gets its own subclass below.
    """

    topic: str
    start_time: str | None = None


class ZoomPastMeetingDetails(ZoomSessionDetails):
    """Response shape of `GET /past_meetings/{meetingId}` — every documented field.

    Zoom documents all of them as always sent, so a missing one means Zoom
    changed the contract. Failing here says so, where a default would instead
    index the meeting under a title nobody chose.
    """

    uuid: str
    id: int
    # A past meeting has already ended, so it always carries both timestamps
    # where a scheduled one may not.
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


class ZoomWebinarDetails(ZoomSessionDetails):
    """Response shape of `GET /webinars/{webinarId}` — every documented scalar
    field.

    This endpoint answers with the webinar's configuration, so most fields
    arrive only when the host turned that feature on. Only the fields that
    identify the webinar are required.

    Zoom also returns `occurrences`, `recurrence`, `settings`,
    `simulive_delay_start` and `tracking_fields`. Nothing here reads them and
    `settings` alone nests 77 more fields, so they are left off rather than
    half-modelled. `occurrences` cannot stand in for
    `/past_webinars/{id}/instances` anyway: it carries `occurrence_id` and the
    transcript call needs the `uuid`.
    """

    id: int
    uuid: str
    host_id: str
    type: int

    agenda: str | None = None
    created_at: str | None = None
    creation_source: str | None = None
    duration: int | None = None
    encrypted_passcode: str | None = None
    h323_passcode: str | None = None
    host_email: str | None = None
    is_simulive: bool | None = None
    join_url: str | None = None
    password: str | None = None
    record_file_id: str | None = None
    registration_url: str | None = None
    start_url: str | None = None
    template_id: str | None = None
    timezone: str | None = None
    transition_to_live: bool | None = None


class ZoomSessionOccurrence(BaseModel):
    """One entry from `GET /past_meetings/{meetingId}/instances` or
    `GET /past_webinars/{webinarId}/instances` — identical shapes under
    different response keys."""

    uuid: str
    start_time: str


class ZoomUser(BaseModel):
    """The fields the connector reads from `GET /users` and from
    `GET /groups/{groupId}/members` — two endpoints that describe a user the
    same way under different response keys."""

    id: str | None = None
    email: str | None = None


class ZoomUserPage(BaseModel):
    users: list[ZoomUser] = Field(default_factory=list)
    next_page_token: str | None = None


class ZoomRecordingEntry(BaseModel):
    """One entry from the `meetings` array of `GET /users/{userId}/recordings`."""

    uuid: str
    # Zoom sends the meeting number as an integer here and as a string everywhere else.
    id: int | str | None = None
    topic: str | None = None
    start_time: str | None = None
    type: int | str | None = None

    @property
    def session_id(self) -> str:
        # A recording uploaded through the web portal has no meeting number.
        return str(self.id) if self.id is not None else self.uuid


class ZoomRecordingPage(BaseModel):
    recordings: list[ZoomRecordingEntry] = Field(default_factory=list)
    next_page_token: str | None = None
