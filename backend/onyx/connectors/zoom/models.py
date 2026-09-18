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
    """A session's transcript, read from the TRANSCRIPT entry of its recording.

    Zoom never sends this shape. It is the one model here that is built rather
    than validated, by `ZoomRecordingEntry.transcript` below.
    """

    download_url: str | None = None
    is_ready: bool = True
    meeting_topic: str | None = None

    @property
    def is_downloadable(self) -> bool:
        return self.is_ready and bool(self.download_url)


class ZoomSessionDetails(BaseModel):
    """The fields both details endpoints always carry. Meetings and webinars
    answer with different shapes, so each gets its own subclass below.
    """

    # Zoom sends the session number as an integer here and as a string
    # everywhere else, so callers read it through session_id.
    id: int
    topic: str
    start_time: str | None = None

    @property
    def session_id(self) -> str:
        return str(self.id)


class ZoomPastMeetingDetails(ZoomSessionDetails):
    """Response shape of `GET /past_meetings/{meetingId}` — every documented field.

    Zoom documents all of them as always sent, so a missing one means Zoom
    changed the contract. Failing here says so, where a default would instead
    index the meeting under a title nobody chose.
    """

    uuid: str
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


TRANSCRIPT_FILE_TYPE = "TRANSCRIPT"
_COMPLETED_FILE_STATUS = "completed"


class ZoomRecordingFile(BaseModel):
    """Every documented field of one entry in a recording's `recording_files`
    array.

    Almost everything is optional because one array holds every file type the
    recording produced, and the odd ones out are validated alongside the
    transcript. Zoom's own text says a CC or TIMELINE entry leaves out `id`,
    `status`, `file_size`, `recording_type` and `play_url`, and a real TIMELINE
    entry arrives without `file_extension` too. Requiring any of those would
    fail the whole recording over a file nothing here reads.
    """

    meeting_id: str
    recording_start: str
    file_type: str

    id: str | None = None
    file_extension: str | None = None
    file_size: int | None = None
    recording_end: str | None = None
    recording_type: str | None = None
    status: str | None = None
    play_url: str | None = None
    # Zoom sends no download_url to an on-premise account. It sends file_path
    # instead, which names a file on the customer's own server.
    download_url: str | None = None
    file_path: str | None = None
    # Only the trash listing carries this.
    deleted_time: str | None = None

    @property
    def is_transcript(self) -> bool:
        return self.file_type.upper() == TRANSCRIPT_FILE_TYPE

    @property
    def is_ready(self) -> bool:
        # A CC or TIMELINE entry carries no status at all, so a missing one
        # cannot mean unfinished.
        return self.status is None or self.status.lower() == _COMPLETED_FILE_STATUS


class ZoomRecordingEntry(BaseModel):
    """Every scalar field of one recording. It arrives as an entry in the
    `meetings` array of `GET /users/{userId}/recordings`, and as the whole body
    of `GET /meetings/{meetingId}/recordings`.

    The per-meeting call also answers with `download_access_token` and
    `password`, both left off on purpose: they are credentials, and a model
    that holds them puts them in every log line that dumps it. Zoom's
    `participant_audio_files` array is left off because nothing reads it.

    Only the fields the recordings listing documents as always sent are
    required. The rest are conditional, and the per-meeting call is the only
    one that sends several of them at all.
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
    service_name: str | None = None
    external_storage_addr: str | None = None

    # Zoom fills these four in for recording-connector meetings only.
    instance_id: str | None = None
    rc_meeting_zone_name: str | None = None
    rc_zone: str | None = None
    zone_instance_id: str | None = None

    recording_files: list[ZoomRecordingFile] = Field(default_factory=list)

    @property
    def session_id(self) -> str:
        # A recording uploaded through the web portal has no meeting number.
        return str(self.id) if self.id is not None else self.uuid

    @property
    def transcript(self) -> ZoomTranscript | None:
        """None means Zoom recorded the session without transcribing it."""
        file = next((f for f in self.recording_files if f.is_transcript), None)
        if file is None:
            return None
        return ZoomTranscript(
            download_url=file.download_url,
            is_ready=file.is_ready,
            meeting_topic=self.topic,
        )


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
