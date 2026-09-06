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
    """Every scalar field of `GET /users`. `GET /groups/{groupId}/members`
    describes a user the same way under a different response key and sends a
    subset of these, so both validate here. `/users` also returns
    custom_attributes, division_ids, group_ids, im_group_ids, license_info_list
    and login_types, all arrays that nothing reads.
    """

    email: str
    type: int
    first_name: str
    last_name: str

    id: str | None = None
    display_name: str | None = None
    status: str | None = None
    role_id: str | None = None
    dept: str | None = None
    timezone: str | None = None
    pmi: int | None = None
    host_key: str | None = None
    employee_unique_id: str | None = None
    plan_united_type: str | None = None
    last_client_version: str | None = None
    last_login_time: str | None = None
    created_at: str | None = None
    user_created_at: str | None = None
    verified: int | None = None


class ZoomUserPage(BaseModel):
    """One page of either user listing. The client builds this rather than
    validating a response, because `/users` and `/groups/{groupId}/members`
    return the same users under different keys.
    """

    users: list[ZoomUser] = Field(default_factory=list)
    next_page_token: str | None = None


class ZoomRecordingEntry(BaseModel):
    """Every scalar field of one entry in the `meetings` array of
    `GET /users/{userId}/recordings`. The entry also carries `recording_files`,
    thirteen more fields describing each file, which nothing here reads.
    """

    uuid: str
    topic: str
    start_time: str
    account_id: str
    host_id: str
    duration: int
    total_size: int
    recording_count: int

    # Zoom sends the meeting number as an integer here and as a string everywhere else.
    id: int | str | None = None
    type: int | str | None = None

    recording_play_passcode: str | None = None
    auto_delete: bool | None = None
    auto_delete_date: str | None = None

    @property
    def session_id(self) -> str:
        # A recording uploaded through the web portal has no meeting number.
        return str(self.id) if self.id is not None else self.uuid


class ZoomRecordingPage(BaseModel):
    """One page of `GET /users/{userId}/recordings`. The client builds this
    rather than validating a response, so Zoom's `from`, `to` and page counters
    are not carried across.
    """

    recordings: list[ZoomRecordingEntry] = Field(default_factory=list)
    next_page_token: str | None = None


class ZoomParticipant(BaseModel):
    """One entry from `GET /past_meetings/{meetingId}/participants` or
    `GET /past_webinars/{webinarId}/participants`."""

    # Zoom blanks this for anyone outside the host's account, so it is not
    # required and callers must cope with an empty string.
    user_email: str | None = None
    name: str | None = None


# Zoom has no cancelled state: cancelling a registration sets the status to
# "denied". The other values are "approved" and "pending".
APPROVED_REGISTRANT_STATUS = "approved"

# Zoom's own error codes, which it sends in the response body under an HTTP 400
# or 404. NOT_ENTITLED really is "200" — it is a Zoom code, not an HTTP status.
# Compare them as text: Zoom sends the code as a number on some endpoints and as
# a string on others.
ZOOM_MEETING_TOO_OLD_CODE = "12702"
ZOOM_NOT_FOUND_CODE = "3001"
ZOOM_NOT_ENTITLED_CODE = "200"


class ZoomRegistrant(BaseModel):
    """One entry from `GET /meetings/{meetingId}/registrants` or
    `GET /webinars/{webinarId}/registrants`."""

    email: str | None = None
    status: str | None = None


class ZoomInvitee(BaseModel):
    """One entry of `settings.meeting_invitees[]` from
    `GET /meetings/{meetingId}`. Webinars have no equivalent field."""

    email: str | None = None
    internal_user: bool = False


class ZoomPanelist(BaseModel):
    """One entry from `GET /webinars/{webinarId}/panelists` — a webinar
    speaker, who does not necessarily register or appear as a participant."""

    email: str | None = None
    name: str | None = None
