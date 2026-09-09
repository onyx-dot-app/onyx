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
    """Every documented field of one entry from
    `GET /past_meetings/{meetingId}/participants` or
    `GET /past_webinars/{webinarId}/participants`. Zoom describes the two
    identically, so both validate here.

    Zoom empties `user_email` for anyone outside the host's account, and `id`
    for anyone who joined without logging in. It sends both fields either way,
    so neither is optional.
    """

    duration: int
    failover: bool
    id: str
    join_time: str
    leave_time: str
    name: str
    status: str
    user_email: str
    user_id: str

    internal_user: bool = False

    # Zoom sends this only when the request asks for it through include_fields.
    registrant_id: str | None = None


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
    """Every documented scalar field of one entry from
    `GET /meetings/{meetingId}/registrants` or
    `GET /webinars/{webinarId}/registrants`. Zoom marks only `email` and
    `first_name` as always sent; the rest are answers to a registration form
    the host can shorten or skip. Zoom also returns `custom_questions`, the
    host's own questions and their answers, which nothing here reads.
    """

    email: str
    first_name: str

    id: str | None = None
    address: str | None = None
    city: str | None = None
    comments: str | None = None
    country: str | None = None
    create_time: str | None = None
    industry: str | None = None
    job_title: str | None = None
    join_url: str | None = None
    last_name: str | None = None
    no_of_employees: str | None = None
    org: str | None = None
    phone: str | None = None
    purchasing_time_frame: str | None = None
    role_in_purchase_process: str | None = None
    state: str | None = None
    status: str | None = None
    zip: str | None = None

    # The webinar listing does not document this one.
    participant_pin_code: int | None = None


class ZoomInvitee(BaseModel):
    """Both documented fields of one entry of `settings.meeting_invitees[]` from
    `GET /meetings/{meetingId}`. Webinars have no equivalent field."""

    email: str
    internal_user: bool = False


class ZoomPanelist(BaseModel):
    """Every documented field of one entry from
    `GET /webinars/{webinarId}/panelists` — a webinar speaker, who does not
    necessarily register or appear as a participant. The name tag and virtual
    background fields arrive only when the host set them up.
    """

    id: str
    email: str
    name: str
    join_url: str

    name_tag_description: str | None = None
    name_tag_id: str | None = None
    name_tag_name: str | None = None
    name_tag_pronouns: str | None = None
    virtual_background_id: str | None = None
