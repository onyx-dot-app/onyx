"""Response models for the Zoom endpoints this connector calls.

These mirror Zoom's documented responses and nothing else. A field is `| None`
only where Zoom types it `string | null`, and it has a default only where
Zoom's own text says the field is conditional or Zoom was seen leaving it out.
"""

from enum import Enum

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
    """A session's transcript. Zoom never sends this shape;
    `ZoomRecordingEntry.transcript` builds it from the recording's file list.
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


class ZoomMeetingDetails(BaseModel):
    """Response of `GET /meetings/{meetingId}`, read for a meeting's host when
    pruning."""

    host_id: str | None = None


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
    return the same users under different keys. `total_records` is carried
    because comparing against it is the only way to catch a listing that
    stopped early.
    """

    users: list[ZoomUser] = Field(default_factory=list)
    next_page_token: str | None = None
    total_records: int | None = None


TRANSCRIPT_FILE_TYPE = "TRANSCRIPT"
_COMPLETED_FILE_STATUS = "completed"


class ZoomRecordingFile(BaseModel):
    """One entry of a recording's `recording_files` array, cut to the fields
    this connector reads."""

    file_type: str

    status: str | None = None
    download_url: str | None = None

    @property
    def is_transcript(self) -> bool:
        return self.file_type.upper() == TRANSCRIPT_FILE_TYPE

    @property
    def is_ready(self) -> bool:
        return self.status is None or self.status.lower() == _COMPLETED_FILE_STATUS


class ZoomRecordingEntry(BaseModel):
    """One recording. Zoom sends it as an entry in the `meetings` array of
    `GET /users/{userId}/recordings`, and as the whole body of
    `GET /meetings/{meetingId}/recordings`.
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
    rather than validating a response, so Zoom's `from` and `to` are not
    carried across. `total_records` is, because comparing against it is the only
    way to catch a listing that stopped early, and pruning deletes every
    recording a listing leaves out.
    """

    recordings: list[ZoomRecordingEntry] = Field(default_factory=list)
    next_page_token: str | None = None
    total_records: int | None = None


# Zoom has no cancelled state: cancelling a registration sets the status to
# "denied". The other values are "approved" and "pending".
APPROVED_REGISTRANT_STATUS = "approved"

# Zoom's own error codes, which it sends in the response body under an HTTP 400
# or 404. NOT_ENTITLED really is "200" — it is a Zoom code, not an HTTP status.
# Compare them as text: Zoom sends the code as a number on some endpoints and as
# a string on others.
ZOOM_MEETING_TOO_OLD_CODE = "12702"
ZOOM_NOT_FOUND_CODE = "3001"
# Zoom's generic bad-request code; only the message says what was wrong.
ZOOM_INVALID_REQUEST_CODE = "300"
ZOOM_USER_NOT_FOUND_CODE = "1001"
ZOOM_NOT_ENTITLED_CODE = "200"
# Undocumented in the spec; the shape is a 400 with a message that lists the
# missing scopes.
ZOOM_MISSING_SCOPE_CODE = "4711"


class ZoomShareRecording(str, Enum):
    """Zoom's enum is closed, so a value outside it fails validation instead of
    being read as shared."""

    PUBLICLY = "publicly"
    INTERNALLY = "internally"
    NONE = "none"


class ZoomRecordingSettings(BaseModel):
    """The fields of `GET /meetings/{meetingId}/recordings/settings` that decide
    who may watch. Zoom marks none of them required or nullable. A recording on
    "Private to me" answers with `share_recording` alone, so the rest default
    to what absence means. The passcode is left out on purpose: it must never
    be logged.
    """

    share_recording: ZoomShareRecording
    recording_authentication: bool = False
    authentication_option: str = ""
    authentication_name: str = ""
    on_demand: bool = False


class ZoomRecordingRegistrant(BaseModel):
    """One viewer who registered to watch, from
    `GET /meetings/{meetingId}/recordings/registrants`. Zoom requires `email`
    but not `status`, and a blank status never counts as approved.
    """

    email: str
    status: str = ""


class ZoomRecordingAuthenticationRule(BaseModel):
    """One sign-in rule from `GET /users/{userId}/settings`. `domains` is comma
    separated and only on a domain rule. `type` stays a plain string so a type
    Zoom adds later fails one rule's lookup rather than the whole catalogue.
    """

    id: str
    type: str = ""
    name: str = ""
    domains: str = ""


class ZoomRecordingAuthenticationSettings(BaseModel):
    """The rules are account-wide, so any one user's answer serves every
    recording."""

    recording_authentication: bool = False
    authentication_options: list[ZoomRecordingAuthenticationRule] = Field(
        default_factory=list
    )
