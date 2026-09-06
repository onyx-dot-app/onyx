import time
from collections.abc import Callable
from datetime import date
from typing import Any, TypeVar
from urllib.parse import quote, urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from onyx.configs.app_configs import REQUEST_TIMEOUT_SECONDS
from onyx.connectors.exceptions import (
    CredentialExpiredError,
    CredentialInvalidError,
    InsufficientPermissionsError,
)
from onyx.connectors.zoom.models import (
    APPROVED_REGISTRANT_STATUS,
    ZOOM_NOT_ENTITLED_CODE,
    ZoomAccessToken,
    ZoomInvitee,
    ZoomPanelist,
    ZoomParticipant,
    ZoomPastMeetingDetails,
    ZoomRecordingPage,
    ZoomRegistrant,
    ZoomSessionOccurrence,
    ZoomTranscript,
    ZoomUser,
    ZoomUserPage,
    ZoomWebinarDetails,
)
from onyx.utils.url import (
    SSRFException,
    ssrf_safe_get,
    validate_outbound_http_url,
)

_OAUTH_TOKEN_URL = "https://zoom.us/oauth/token"
_API_BASE_URL = "https://api.zoom.us/v2"

_ZOOM_HOST = "zoom.us"

_TOKEN_REFRESH_MARGIN_SECONDS = 60

_WEBINAR_ACCESS_HINT = (
    "Zoom refused a webinar request. Webinars need the Webinar add-on enabled for "
    "the host, and the app needs the webinar:read:admin scope. Meetings need "
    "neither, so credentials that read meetings can still fail here."
)

# Zoom caps page_size at 300 on every listing this client pages through.
_MAX_PAGE_SIZE = 300

# A next_page_token dies 15 minutes after Zoom issues it, so an access list is
# paged straight through here instead of being resumed from the checkpoint. This
# bound only stops a broken cursor looping forever: at 300 people per page it is
# far larger than any real session, so lowering it would silently cut people out
# of an access list.
_MAX_ACCESS_LIST_PAGES = 200

_AccessRecordT = TypeVar("_AccessRecordT")


def _encode_path_segment(value: str) -> str:
    return quote(value, safe="")


def _encode_meeting_identifier(identifier: str) -> str:
    """Zoom requires a UUID to be encoded twice when it starts with "/" or
    contains "//"."""
    encoded = _encode_path_segment(identifier)
    if identifier.startswith("/") or "//" in identifier:
        encoded = _encode_path_segment(encoded)
    return encoded


def _next_page_token(body: dict[str, Any]) -> str | None:
    """Zoom ends a listing with an empty string instead of dropping the field, and
    sending that empty token back asks for page one again, forever."""
    return body.get("next_page_token") or None


def _reject_non_zoom_download_url(download_url: str) -> None:
    """The download sends the account-wide bearer token, so a tampered URL would
    hand that credential to whatever host it names. Only the first host needs
    checking, because requests drops the header on a cross-host redirect.
    """
    host = (urlparse(download_url).hostname or "").rstrip(".").lower()
    if host != _ZOOM_HOST and not host.endswith(f".{_ZOOM_HOST}"):
        raise ValueError(
            f"Refusing to send Zoom credentials to a non-Zoom host: {host or download_url!r}"
        )

    try:
        validate_outbound_http_url(download_url, https_only=True)
    except (SSRFException, ValueError) as e:
        raise ValueError(f"Unsafe Zoom transcript download URL: {e}") from e


def _raise_for_zoom_error(response: requests.Response, description: str) -> None:
    """requests' own message stops at "400 Client Error" and drops Zoom's
    explanation, which is where codes like 12702 (meeting over a year old) live.
    """
    if response.ok:
        return

    try:
        body = response.json()
    except ValueError:
        body = None

    detail = ""
    if isinstance(body, dict) and body.get("message"):
        detail = f": {body['message']} (Zoom code {body.get('code')})"

    raise requests.HTTPError(
        f"{response.status_code} from {description}{detail}", response=response
    )


class ZoomClient:
    def __init__(self, account_id: str, client_id: str, client_secret: str) -> None:
        self.account_id = account_id
        self.client_id = client_id
        self.client_secret = client_secret

        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

        self._session = requests.Session()
        retry_strategy = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
        )
        # Mount on the scheme, not per URL: the API, token endpoint and download
        # are three different Zoom hosts, and a missed one silently gets no retries.
        self._session.mount("https://", HTTPAdapter(max_retries=retry_strategy))

    def _fetch_access_token(self) -> str:
        response = self._session.post(
            _OAUTH_TOKEN_URL,
            params={
                "grant_type": "account_credentials",
                "account_id": self.account_id,
            },
            auth=(self.client_id, self.client_secret),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        # A Server-to-Server client secret never expires, so this 401 is invalid,
        # not expired. The 401 in _send_authorized is a real token expiry.
        if response.status_code == 401:
            raise CredentialInvalidError(
                "Zoom rejected the Server-to-Server OAuth client credentials"
            )
        if response.status_code == 403:
            raise InsufficientPermissionsError(
                "Zoom refused to issue a token for this app — check that it is "
                "activated and its scopes are granted"
            )
        _raise_for_zoom_error(response, "the OAuth token request")

        token = ZoomAccessToken.model_validate(response.json())
        self._access_token = token.access_token
        self._token_expires_at = time.monotonic() + token.expires_in
        return token.access_token

    def _get_access_token(self) -> str:
        if (
            self._access_token is None
            or time.monotonic()
            >= self._token_expires_at - _TOKEN_REFRESH_MARGIN_SECONDS
        ):
            return self._fetch_access_token()
        return self._access_token

    def _send_authorized(
        self, description: str, send: Callable[[str], requests.Response]
    ) -> requests.Response:
        """Zoom sometimes rejects a token before the expiry it gave us, so retry
        once with a fresh one. Reporting the 401 instead raises
        CredentialExpiredError, and five of those in a row mark the connector
        invalid and email the admins.
        """
        response = send(self._get_access_token())
        if response.status_code == 401:
            self._access_token = None
            response = send(self._get_access_token())

        if response.status_code == 401:
            raise CredentialExpiredError(
                f"Zoom rejected {description} as unauthorized, even with a fresh token"
            )
        if response.status_code == 403:
            raise InsufficientPermissionsError(
                f"Zoom denied access to {description} — check the app's granted scopes"
            )
        return response

    def _request(self, method: str, endpoint: str, **kwargs: Any) -> requests.Response:
        url = f"{_API_BASE_URL}{endpoint}"
        headers = kwargs.pop("headers", {})

        def send(token: str) -> requests.Response:
            return self._session.request(
                method,
                url,
                headers={**headers, "Authorization": f"Bearer {token}"},
                timeout=REQUEST_TIMEOUT_SECONDS,
                **kwargs,
            )

        return self._send_authorized(endpoint, send)

    def _request_webinar(
        self, endpoint: str, params: dict[str, Any] | None = None
    ) -> requests.Response:
        """Every webinar endpoint fails the same way without the Webinar add-on,
        and the generic scope message sends the admin to check scopes that are
        already correct.
        """
        try:
            response = self._request("GET", endpoint, params=params or {})
        except InsufficientPermissionsError as e:
            raise InsufficientPermissionsError(f"{_WEBINAR_ACCESS_HINT} ({e})") from e

        if response.status_code == 400:
            denial = self._not_entitled_message(response)
            if denial is not None:
                # Zoom's message names the user whose licence is missing, which
                # the hint can't know.
                raise InsufficientPermissionsError(
                    f"{_WEBINAR_ACCESS_HINT} Zoom said: {denial}"
                )
        return response

    @staticmethod
    def _not_entitled_message(response: requests.Response) -> str | None:
        try:
            body = response.json()
        except ValueError:
            return None
        if not isinstance(body, dict):
            return None
        if str(body.get("code")) != ZOOM_NOT_ENTITLED_CODE:
            return None
        return str(body.get("message") or "no permission")

    def get_meeting_transcript(self, meeting_identifier: str) -> ZoomTranscript:
        """Takes a meeting ID, a webinar ID, or one occurrence's UUID. Zoom has
        no webinar transcript endpoint, so webinars come through here too.

        A session that was never recorded answers 404, which raises here. Whether
        that is a skip or a failure is the caller's call, not this client's.
        """
        response = self._request(
            "GET",
            f"/meetings/{_encode_meeting_identifier(meeting_identifier)}/transcript",
        )
        _raise_for_zoom_error(response, f"the transcript for {meeting_identifier}")
        return ZoomTranscript.model_validate(response.json())

    def get_past_meeting_details(
        self, meeting_identifier: str
    ) -> ZoomPastMeetingDetails:
        response = self._request(
            "GET", f"/past_meetings/{_encode_meeting_identifier(meeting_identifier)}"
        )
        _raise_for_zoom_error(response, f"the details for {meeting_identifier}")
        return ZoomPastMeetingDetails.model_validate(response.json())

    def list_past_meeting_occurrences(
        self, meeting_id: str
    ) -> list[ZoomSessionOccurrence]:
        """A recurring meeting records each run separately, and the bare
        meeting_id only ever reaches the latest one, so call this first for every
        occurrence's UUID. This endpoint is not paginated. Zoom returns nothing
        for meetings older than 15 months, silently and with no way to detect it,
        so scope by host or group to reach further back.
        """
        response = self._request(
            "GET",
            f"/past_meetings/{_encode_meeting_identifier(meeting_id)}/instances",
        )
        _raise_for_zoom_error(response, f"the occurrences for {meeting_id}")
        occurrences = response.json().get("meetings", [])
        return [ZoomSessionOccurrence.model_validate(o) for o in occurrences]

    def get_webinar_details(self, webinar_identifier: str) -> ZoomWebinarDetails:
        """Takes a webinar ID or one occurrence's UUID. Zoom has no
        `/past_webinars/{id}` to match the meeting details endpoint, so a past
        occurrence is read back through this one.
        """
        response = self._request_webinar(
            f"/webinars/{_encode_meeting_identifier(webinar_identifier)}"
        )
        _raise_for_zoom_error(response, f"the details for webinar {webinar_identifier}")
        return ZoomWebinarDetails.model_validate(response.json())

    def list_past_webinar_occurrences(
        self, webinar_id: str
    ) -> list[ZoomSessionOccurrence]:
        """Unlike the meeting equivalent, this endpoint declares no age limit,
        so webinar history is not cut off at 15 months.

        An unknown webinar answers 404, which raises here rather than reading as
        a webinar that ran no times.
        """
        response = self._request_webinar(
            f"/past_webinars/{_encode_meeting_identifier(webinar_id)}/instances"
        )
        _raise_for_zoom_error(response, f"the occurrences for webinar {webinar_id}")
        occurrences = response.json().get("webinars", [])
        return [ZoomSessionOccurrence.model_validate(o) for o in occurrences]

    def list_group_members(
        self, group_id: str, page_token: str | None = None
    ) -> ZoomUserPage:
        """Zoom cannot grant a session to a Group, so a Group only ever scopes
        Discovery here and this must never be used as an access list."""
        params: dict[str, Any] = {"page_size": _MAX_PAGE_SIZE}
        if page_token:
            params["next_page_token"] = page_token

        response = self._request(
            "GET", f"/groups/{_encode_path_segment(group_id)}/members", params=params
        )
        _raise_for_zoom_error(response, f"the members of group {group_id}")
        body = response.json()
        return ZoomUserPage(
            users=[ZoomUser.model_validate(m) for m in body.get("members", [])],
            next_page_token=_next_page_token(body),
        )

    def list_users(self, page_token: str | None = None) -> ZoomUserPage:
        """Zoom never documents that the `{userId}` path parameter accepts an email
        address, so a host allowlist is matched against this listing instead."""
        params: dict[str, Any] = {"page_size": _MAX_PAGE_SIZE}
        if page_token:
            params["next_page_token"] = page_token

        response = self._request("GET", "/users", params=params)
        _raise_for_zoom_error(response, "the account's users")
        body = response.json()
        return ZoomUserPage(
            users=[ZoomUser.model_validate(u) for u in body.get("users", [])],
            next_page_token=_next_page_token(body),
        )

    def list_user_recordings(
        self,
        user_id: str,
        from_date: date,
        to_date: date,
        page_token: str | None = None,
    ) -> ZoomRecordingPage:
        """A 404 here is not "nothing to index": Zoom sends it when the user id
        doesn't exist, so swallowing it would turn a mistyped host email into an
        empty index with nothing to explain it."""
        params: dict[str, Any] = {
            "from": from_date.isoformat(),
            "to": to_date.isoformat(),
            "page_size": _MAX_PAGE_SIZE,
        }
        if page_token:
            params["next_page_token"] = page_token

        response = self._request(
            "GET", f"/users/{_encode_path_segment(user_id)}/recordings", params=params
        )
        _raise_for_zoom_error(response, f"the recordings for user {user_id}")
        body = response.json()
        return ZoomRecordingPage(
            recordings=body.get("meetings", []),
            next_page_token=_next_page_token(body),
        )

    def _request_meeting(
        self, endpoint: str, params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("GET", endpoint, params=params or {})

    def _list_access_pages(
        self,
        description: str,
        endpoint: str,
        request: Callable[[str, dict[str, Any] | None], requests.Response],
        response_key: str,
        parse: Callable[[Any], _AccessRecordT],
        extra_params: dict[str, Any] | None = None,
    ) -> list[_AccessRecordT]:
        """Drains every page in one go. A 404 or an empty page is a normal answer
        for these endpoints: Zoom returns nothing for a session with a single
        attendee, or one where registration was never turned on.
        """
        records: list[_AccessRecordT] = []
        page_token: str | None = None

        for _ in range(_MAX_ACCESS_LIST_PAGES):
            params: dict[str, Any] = {
                "page_size": _MAX_PAGE_SIZE,
                **(extra_params or {}),
            }
            if page_token:
                params["next_page_token"] = page_token

            response = request(endpoint, params)
            if response.status_code == 404:
                return records
            _raise_for_zoom_error(response, description)

            body = response.json()
            records.extend(parse(entry) for entry in body.get(response_key, []))
            page_token = _next_page_token(body)
            if not page_token:
                return records

        raise ValueError(f"Zoom kept paging {description} past the page limit")

    def list_past_meeting_participants(
        self, occurrence_uuid: str
    ) -> list[ZoomParticipant]:
        """This is the only access source with an age limit: Zoom deletes
        attendance after the retention window and then answers 400 with code
        12702. Registrants and invitees still answer for the same old meeting."""
        identifier = _encode_meeting_identifier(occurrence_uuid)
        return self._list_access_pages(
            f"the participants of meeting {occurrence_uuid}",
            f"/past_meetings/{identifier}/participants",
            self._request_meeting,
            "participants",
            ZoomParticipant.model_validate,
        )

    def list_past_webinar_participants(
        self, occurrence_uuid: str
    ) -> list[ZoomParticipant]:
        identifier = _encode_meeting_identifier(occurrence_uuid)
        return self._list_access_pages(
            f"the participants of webinar {occurrence_uuid}",
            f"/past_webinars/{identifier}/participants",
            self._request_webinar,
            "participants",
            ZoomParticipant.model_validate,
        )

    def list_meeting_registrants(self, meeting_id: str) -> list[ZoomRegistrant]:
        """Registrants belong to the scheduled meeting, not to one occurrence, so
        a recurring series returns the same list for every run. The status
        parameter only narrows what Zoom sends, so each record keeps its own
        status for the caller to check."""
        identifier = _encode_meeting_identifier(meeting_id)
        return self._list_access_pages(
            f"the registrants of meeting {meeting_id}",
            f"/meetings/{identifier}/registrants",
            self._request_meeting,
            "registrants",
            ZoomRegistrant.model_validate,
            extra_params={"status": APPROVED_REGISTRANT_STATUS},
        )

    def list_webinar_registrants(self, webinar_id: str) -> list[ZoomRegistrant]:
        identifier = _encode_meeting_identifier(webinar_id)
        return self._list_access_pages(
            f"the registrants of webinar {webinar_id}",
            f"/webinars/{identifier}/registrants",
            self._request_webinar,
            "registrants",
            ZoomRegistrant.model_validate,
            extra_params={"status": APPROVED_REGISTRANT_STATUS},
        )

    def list_meeting_invitees(self, meeting_id: str) -> list[ZoomInvitee]:
        """Who was invited, which is not the same as who turned up. The list
        hangs off the scheduled meeting, so a recurring series has one covering
        every run and an ad-hoc meeting has none at all. There is no age limit
        here, so an old meeting still answers.
        """
        identifier = _encode_meeting_identifier(meeting_id)
        response = self._request("GET", f"/meetings/{identifier}")
        if response.status_code == 404:
            return []
        _raise_for_zoom_error(response, f"the details for meeting {meeting_id}")

        settings = response.json().get("settings") or {}
        return [
            ZoomInvitee.model_validate(i) for i in settings.get("meeting_invitees", [])
        ]

    def list_webinar_panelists(self, webinar_id: str) -> list[ZoomPanelist]:
        """A panelist does not have to register, so without this a presenter is
        missing from the access list of a webinar they spoke at. Not paginated.
        """
        identifier = _encode_meeting_identifier(webinar_id)
        response = self._request_webinar(f"/webinars/{identifier}/panelists")
        if response.status_code == 404:
            return []
        _raise_for_zoom_error(response, f"the panelists of webinar {webinar_id}")
        return [
            ZoomPanelist.model_validate(p) for p in response.json().get("panelists", [])
        ]

    def download_transcript_vtt(self, download_url: str) -> str:
        """The download redirects to a storage host, so every hop is checked
        before it is followed — an open redirect on a Zoom host would otherwise
        make this connector fetch private addresses. The token goes only to the
        Zoom host checked up front, since the storage host authenticates from
        the signed URL.
        """
        _reject_non_zoom_download_url(download_url)

        def send(token: str) -> requests.Response:
            return self._session.get(
                download_url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=REQUEST_TIMEOUT_SECONDS,
                allow_redirects=False,
            )

        response = self._send_authorized("the transcript download", send)
        if response.is_redirect:
            location = urljoin(download_url, response.headers["Location"])
            try:
                response = ssrf_safe_get(
                    location,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                    https_only=True,
                )
            except SSRFException as e:
                raise ValueError(
                    f"Zoom redirected the transcript download somewhere unsafe: {e}"
                ) from e

        _raise_for_zoom_error(response, "the transcript download")
        return response.text
