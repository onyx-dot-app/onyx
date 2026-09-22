import time
from collections.abc import Callable
from datetime import date, datetime
from typing import Any, TypeVar
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter

from onyx.configs.app_configs import REQUEST_TIMEOUT_SECONDS
from onyx.connectors.exceptions import (
    CredentialExpiredError,
    CredentialInvalidError,
    InsufficientPermissionsError,
)
from onyx.connectors.zoom import endpoints
from onyx.connectors.zoom.endpoints import (
    ENTITLEMENT_HINTS,
    ZoomEndpoint,
    ZoomEntitlement,
)
from onyx.connectors.zoom.models import (
    ZOOM_INVALID_REQUEST_CODE,
    ZOOM_MISSING_SCOPE_CODE,
    ZOOM_NOT_ENTITLED_CODE,
    ZoomAccessToken,
    ZoomMeetingDetails,
    ZoomPanelist,
    ZoomParticipant,
    ZoomPastMeetingDetails,
    ZoomRecordingAuthenticationSettings,
    ZoomRecordingEntry,
    ZoomRecordingPage,
    ZoomRecordingRegistrant,
    ZoomRecordingSettings,
    ZoomRegistrant,
    ZoomSessionOccurrence,
    ZoomUser,
    ZoomUserPage,
    ZoomWebinarDetails,
)
from onyx.connectors.zoom.rate_limit import (
    ZoomRateLimiter,
    ZoomRateLimitSettings,
)
from onyx.utils.logger import setup_logger
from onyx.utils.url import (
    SSRFException,
    ssrf_safe_get,
    validate_outbound_http_url,
)

logger = setup_logger()

_ZOOM_HOST = "zoom.us"

_TOKEN_REFRESH_MARGIN_SECONDS = 60

# Zoom's date-scoped query parameters are whole UTC days.
_ZOOM_DATE_FORMAT = "%Y-%m-%d"

# Zoom caps page_size at 300 on every listing this client pages through.
_MAX_PAGE_SIZE = 300

# Backstop for a cursor that keeps advancing forever; the cycle check in
# _paginate catches one that repeats. A Celery task has no working time limit,
# so nothing else would stop either loop. Tripping this drops the document
# rather than truncating its access list.
MAX_LISTING_PAGES = 200

_AccessRecordT = TypeVar("_AccessRecordT")
_RegistrantT = TypeVar("_RegistrantT")


class ZoomNotEntitledError(InsufficientPermissionsError):
    """The account's plan or licence does not cover an endpoint, which no retry
    and no scope change can fix. Kept apart from a missing scope so a caller can
    carry on without the data instead of failing the run."""


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


def _zoom_body(response: requests.Response) -> dict[str, Any] | None:
    try:
        body = response.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def _not_entitled_message(response: requests.Response) -> str | None:
    body = _zoom_body(response)
    if body is None or str(body.get("code")) != ZOOM_NOT_ENTITLED_CODE:
        return None
    return str(body.get("message") or "no permission")


# Zoom words the same answer differently for a session and for its recording.
_REGISTRATION_OFF_MESSAGES = (
    "registration has not been enabled",
    "has not registration required",
)


def _registration_not_enabled(error: requests.HTTPError) -> bool:
    """Zoom answers a session or recording that never had registration switched
    on with a 400 and its generic code 300, not with an empty list, so only the
    message tells this apart from a malformed id."""
    response = error.response
    if response is None or response.status_code != 400:
        return False
    body = _zoom_body(response)
    if body is None or str(body.get("code")) != ZOOM_INVALID_REQUEST_CODE:
        return False
    message = str(body.get("message", "")).lower()
    return any(wording in message for wording in _REGISTRATION_OFF_MESSAGES)


def _missing_scope_message(response: requests.Response) -> str | None:
    body = _zoom_body(response)
    if body is None or str(body.get("code")) != ZOOM_MISSING_SCOPE_CODE:
        return None
    return str(body.get("message") or "the token does not carry the scope")


def _zoom_explanation(response: requests.Response) -> str:
    """The API answers `{"code", "message"}`; the OAuth token endpoint answers
    `{"error", "reason"}`. Either way this is the text the admin has to read."""
    try:
        body = response.json()
    except ValueError:
        return ""
    if not isinstance(body, dict):
        return ""
    if body.get("message"):
        return f"{body['message']} (Zoom code {body.get('code')})"
    if body.get("reason"):
        return f"{body['reason']} ({body.get('error')})"
    return ""


def _raise_for_zoom_error(response: requests.Response, description: str) -> None:
    """requests' own message stops at "400 Client Error" and drops Zoom's
    explanation, which is where codes like 12702 (meeting over a year old) live.
    """
    if response.ok:
        return

    detail = _zoom_explanation(response)
    if detail:
        detail = f": {detail}"

    raise requests.HTTPError(
        f"{response.status_code} from {description}{detail}", response=response
    )


# Zoom answers a wrong secret, a wrong account id and a deactivated app all
# with 400. Only the reason text tells them apart, and only the disabled app
# is fixed somewhere other than the credential form.
_APP_DISABLED_REASONS = ("disabled", "not activated", "deactivated")


def _raise_for_token_refusal(response: requests.Response) -> None:
    detail = _zoom_explanation(response)
    suffix = f": {detail}" if detail else ""
    reason = detail.lower()

    if any(marker in reason for marker in _APP_DISABLED_REASONS):
        raise InsufficientPermissionsError(
            "Zoom refused to issue a token because the Server-to-Server OAuth "
            f"app is not activated. Activate it in the Zoom Marketplace{suffix}"
        )
    if "bad request" in reason or "invalid_request" in reason:
        raise CredentialInvalidError(
            "Zoom rejected the token request. This usually means the Account ID "
            f"is wrong{suffix}"
        )
    raise CredentialInvalidError(
        f"Zoom rejected the Server-to-Server OAuth client credentials{suffix}"
    )


class ZoomClient:
    def __init__(
        self,
        account_id: str,
        client_id: str,
        client_secret: str,
        rate_limit_settings: ZoomRateLimitSettings | None = None,
    ) -> None:
        self.account_id = account_id
        self.client_id = client_id
        self.client_secret = client_secret

        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

        self._rate_limiter = ZoomRateLimiter(
            rate_limit_settings or ZoomRateLimitSettings()
        )

        # urllib3 re-sends inside one call, which skips the pacer, and Zoom
        # counts a request it received however slowly it answered. So nothing
        # retries here: ZoomRateLimiter sends every attempt, a slot each.
        self._session = requests.Session()
        for scheme in ("https://", "http://"):
            self._session.mount(scheme, HTTPAdapter(max_retries=0))

    def _fetch_access_token(self) -> str:
        endpoint = endpoints.OAUTH_TOKEN
        description = endpoint.description()
        response = self._rate_limiter.call(
            description,
            endpoint.tier,
            lambda: self._session.post(
                endpoint.url(),
                params={
                    "grant_type": "account_credentials",
                    "account_id": self.account_id,
                },
                auth=(self.client_id, self.client_secret),
                timeout=REQUEST_TIMEOUT_SECONDS,
            ),
        )
        # A Server-to-Server client secret never expires, so a refusal here is
        # invalid, not expired. The 401 in _send_authorized is a real expiry.
        if response.status_code in (400, 401):
            _raise_for_token_refusal(response)
        if response.status_code == 403:
            raise InsufficientPermissionsError(
                "Zoom refused to issue a token for this app — check that it is "
                "activated and its scopes are granted"
            )
        _raise_for_zoom_error(response, description)

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

    def check_credentials(self) -> None:
        """Skips the cached token on purpose: a secret rotated an hour ago would
        still pass otherwise."""
        self._fetch_access_token()

    def _send_authorized(
        self,
        endpoint: ZoomEndpoint,
        description: str,
        send: Callable[[str], requests.Response],
    ) -> requests.Response:
        """Zoom sometimes rejects a token before the expiry it gave us, so retry
        once with a fresh one. Reporting the 401 instead raises
        CredentialExpiredError, and five of those in a row mark the connector
        invalid and email the admins.

        Pacing sits here so that a page of a listing and this 401 re-send each
        count as the separate HTTP request they are.
        """

        def paced(token: str) -> requests.Response:
            return self._rate_limiter.call(
                description, endpoint.tier, lambda: send(token)
            )

        response = paced(self._get_access_token())
        if response.status_code == 401:
            self._access_token = None
            response = paced(self._get_access_token())

        if response.status_code == 401:
            raise CredentialExpiredError(
                f"Zoom rejected {description} as unauthorized, even with a fresh token"
            )
        if response.status_code == 403:
            raise self._entitlement_aware_denial(endpoint, description)
        # Zoom reports a missing scope as a 400, not a 403, so without this it
        # would read as a bad request and never reach the admin as a scope fix.
        if response.status_code == 400:
            missing = _missing_scope_message(response)
            if missing is not None:
                raise InsufficientPermissionsError(
                    f"Zoom denied {description}: {missing}. Grant the scope on the "
                    "Server-to-Server OAuth app in the Zoom Marketplace."
                )
        return response

    @staticmethod
    def _entitlement_aware_denial(
        endpoint: ZoomEndpoint, description: str
    ) -> InsufficientPermissionsError:
        """A 403 on an entitled endpoint is usually the missing add-on rather
        than a missing scope, and the generic message sends the admin to
        re-check scopes that are already correct. Either way it names Zoom's
        operation, because the admin has to know which call was refused.
        """
        denied = f"Zoom denied access to {description}"
        if endpoint.operation:
            denied = f"{denied} ({endpoint.operation})"

        hint = ENTITLEMENT_HINTS.get(endpoint.requires)
        if hint is not None:
            return InsufficientPermissionsError(f"{hint} ({denied})")
        return InsufficientPermissionsError(
            f"{denied} — check the app's granted scopes"
        )

    def _get(
        self,
        endpoint: ZoomEndpoint,
        identifier: str = "",
        params: dict[str, Any] | None = None,
    ) -> requests.Response:
        description = endpoint.description(identifier)
        url = endpoint.url(identifier)

        def send(token: str) -> requests.Response:
            return self._session.request(
                "GET",
                url,
                headers={"Authorization": f"Bearer {token}"},
                params=params or {},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )

        response = self._send_authorized(endpoint, description, send)

        if endpoint.requires is not ZoomEntitlement.NONE and (
            response.status_code == 400
        ):
            denial = _not_entitled_message(response)
            if denial is not None:
                # Zoom's message names the user whose licence is missing, which
                # the hint can't know.
                hint = ENTITLEMENT_HINTS[endpoint.requires]
                raise ZoomNotEntitledError(f"{hint} Zoom said: {denial}")

        _raise_for_zoom_error(response, description)
        return response

    def _paginate(
        self,
        endpoint: ZoomEndpoint,
        identifier: str,
        response_key: str,
        parse: Callable[[Any], _AccessRecordT],
        extra_params: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> list[_AccessRecordT]:
        """Zoom's next_page_token expires 15 minutes after it is issued, so the
        whole list is drained here rather than resumed from the checkpoint. A
        limit stops after that many records, for a caller that only needs to
        see Zoom answer."""
        if limit is not None and limit < 1:
            raise ValueError(f"A listing limit must be at least 1, got {limit}")
        records: list[_AccessRecordT] = []
        page_token: str | None = None
        seen_tokens: set[str] = set()
        page_size = _MAX_PAGE_SIZE if limit is None else min(_MAX_PAGE_SIZE, limit)

        for _ in range(MAX_LISTING_PAGES):
            params: dict[str, Any] = {
                "page_size": page_size,
                **(extra_params or {}),
            }
            if page_token:
                params["next_page_token"] = page_token

            body = self._get(endpoint, identifier, params).json()
            records.extend(parse(entry) for entry in body.get(response_key, []))

            page_token = _next_page_token(body)
            if limit is not None and len(records) >= limit:
                return records[:limit]
            if not page_token:
                return records
            if page_token in seen_tokens:
                raise ValueError(
                    "Zoom stopped advancing the cursor for "
                    f"{endpoint.description(identifier)}"
                )
            seen_tokens.add(page_token)

        raise ValueError(
            f"Zoom kept paging {endpoint.description(identifier)} past "
            f"{MAX_LISTING_PAGES} pages"
        )

    def get_recording(self, meeting_identifier: str) -> ZoomRecordingEntry:
        """Takes a meeting ID, a webinar ID, or one occurrence's UUID. Webinars
        come here too because Zoom has no webinar equivalent of this endpoint.

        A session with no cloud recording at all answers 404, which raises.

        Do not switch this to `GET /meetings/{meetingId}/transcript`. Against a
        live account that answered 404 for a session whose VTT was sitting in
        `recording_files`.
        """
        response = self._get(endpoints.MEETING_RECORDINGS, meeting_identifier)
        return ZoomRecordingEntry.model_validate(response.json())

    def get_recording_settings(self, meeting_identifier: str) -> ZoomRecordingSettings:
        """Takes the occurrence UUID, or a meeting or webinar number for that
        session's latest recording. A session with no cloud recording answers
        404, which raises."""
        response = self._get(endpoints.RECORDING_SETTINGS, meeting_identifier)
        return ZoomRecordingSettings.model_validate(response.json())

    def list_recording_registrants(
        self,
        meeting_identifier: str,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[ZoomRecordingRegistrant]:
        """The viewers who registered to watch, when the owner switched that on.
        With it off Zoom answers a 400 rather than an empty list, and that reads
        here as nobody registered. Zoom's reference names only the meeting
        number here, but against a live account the occurrence UUID answered the
        same way as it does for the settings endpoint, and the number would
        point at the series' latest recording instead of the sampled one."""
        return self._list_registrants(
            endpoints.RECORDING_REGISTRANTS,
            meeting_identifier,
            status,
            ZoomRecordingRegistrant.model_validate,
            limit=limit,
        )

    def get_recording_authentication_rules(
        self, user_id: str
    ) -> ZoomRecordingAuthenticationSettings:
        """A recording's own settings name its rule but leave out the rule's
        type and domains, so those come from here. Rules are account-wide, so
        any user's answer serves the whole run."""
        response = self._get(
            endpoints.USER_SETTINGS, user_id, {"option": "recording_authentication"}
        )
        return ZoomRecordingAuthenticationSettings.model_validate(response.json())

    def get_meeting_details(self, meeting_id: str) -> ZoomMeetingDetails:
        """The scheduled meeting. `get_past_meeting_details` is the occurrence
        equivalent and answers for a meeting this one has stopped knowing."""
        response = self._get(endpoints.MEETING_DETAILS, meeting_id)
        return ZoomMeetingDetails.model_validate(response.json())

    def get_past_meeting_details(
        self, meeting_identifier: str
    ) -> ZoomPastMeetingDetails:
        response = self._get(endpoints.PAST_MEETING_DETAILS, meeting_identifier)
        return ZoomPastMeetingDetails.model_validate(response.json())

    def list_past_meeting_occurrences(
        self,
        meeting_id: str,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> list[ZoomSessionOccurrence]:
        """A recurring meeting records each run separately, and the bare
        meeting_id only ever reaches the latest one, so call this first for every
        occurrence's UUID. This endpoint is not paginated. Zoom returns nothing
        for meetings older than 15 months, silently and with no way to detect it,
        so scope by host or group to reach further back.

        Zoom ignores from/to unless both are sent, and reads them as whole UTC
        days, so the reply still overshoots a sub-day window at either end and
        the caller trims it.
        """
        params: dict[str, str] = {}
        if window_start is not None and window_end is not None:
            params = {
                "from": window_start.strftime(_ZOOM_DATE_FORMAT),
                "to": window_end.strftime(_ZOOM_DATE_FORMAT),
            }

        response = self._get(endpoints.PAST_MEETING_OCCURRENCES, meeting_id, params)
        occurrences = response.json().get("meetings", [])
        return [ZoomSessionOccurrence.model_validate(o) for o in occurrences]

    def get_webinar_details(self, webinar_identifier: str) -> ZoomWebinarDetails:
        """Takes a webinar ID or one occurrence's UUID. Zoom has no
        `/past_webinars/{id}` to match the meeting details endpoint, so a past
        occurrence is read back through this one.
        """
        response = self._get(endpoints.WEBINAR_DETAILS, webinar_identifier)
        return ZoomWebinarDetails.model_validate(response.json())

    def list_past_webinar_occurrences(
        self, webinar_id: str
    ) -> list[ZoomSessionOccurrence]:
        """Unlike the meeting equivalent, this endpoint declares no age limit,
        so webinar history is not cut off at 15 months.

        An unknown webinar answers 404, which raises here rather than reading as
        a webinar that ran no times.
        """
        response = self._get(endpoints.PAST_WEBINAR_OCCURRENCES, webinar_id)
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

        body = self._get(endpoints.GROUP_MEMBERS, group_id, params).json()
        return ZoomUserPage(
            users=[ZoomUser.model_validate(m) for m in body.get("members", [])],
            next_page_token=_next_page_token(body),
            total_records=body.get("total_records"),
        )

    def get_user(self, user_id: str) -> ZoomUser:
        """One user by id, whatever their status: a recording outlives its
        owner's deactivation, and the listing shows active users only. A user
        Zoom has no record of answers 404 with code 1001, which raises."""
        response = self._get(endpoints.USER, user_id)
        return ZoomUser.model_validate(response.json())

    def list_users(
        self, page_token: str | None = None, *, page_size: int = _MAX_PAGE_SIZE
    ) -> ZoomUserPage:
        """Host emails are matched against this listing to get the user ids the
        recordings listing is called with. TODO(subash): that listing documents
        its `userId` as "ID or email address", so discovery could pass the email
        and drop this call and its `user:read:list_users:admin` scope."""
        params: dict[str, Any] = {"page_size": page_size}
        if page_token:
            params["next_page_token"] = page_token

        body = self._get(endpoints.USERS, params=params).json()
        return ZoomUserPage(
            users=[ZoomUser.model_validate(u) for u in body.get("users", [])],
            next_page_token=_next_page_token(body),
            total_records=body.get("total_records"),
        )

    def list_user_recordings(
        self,
        user_id: str,
        from_date: date,
        to_date: date,
        page_token: str | None = None,
    ) -> ZoomRecordingPage:
        """Zoom takes an email here as well as a user id, and covers at most a
        month per call.

        A 404 is not "nothing to index": Zoom sends it when the user does not
        exist, so swallowing it would turn a mistyped host email into an empty
        index with nothing to explain it."""
        params: dict[str, Any] = {
            "from": from_date.isoformat(),
            "to": to_date.isoformat(),
            "page_size": _MAX_PAGE_SIZE,
        }
        if page_token:
            params["next_page_token"] = page_token

        body = self._get(endpoints.USER_RECORDINGS, user_id, params).json()
        return ZoomRecordingPage(
            recordings=body.get("meetings", []),
            next_page_token=_next_page_token(body),
            total_records=body.get("total_records"),
        )

    def list_past_meeting_participants(
        self, occurrence_uuid: str
    ) -> list[ZoomParticipant]:
        """This is the only access source with an age limit: Zoom deletes
        attendance after the retention window and then answers 400 with code
        12702. Registrants and invitees still answer for the same old meeting."""
        return self._paginate(
            endpoints.PAST_MEETING_PARTICIPANTS,
            occurrence_uuid,
            "participants",
            ZoomParticipant.model_validate,
        )

    def list_past_webinar_participants(
        self, occurrence_uuid: str
    ) -> list[ZoomParticipant]:
        return self._paginate(
            endpoints.PAST_WEBINAR_PARTICIPANTS,
            occurrence_uuid,
            "participants",
            ZoomParticipant.model_validate,
        )

    def _list_registrants(
        self,
        endpoint: ZoomEndpoint,
        identifier: str,
        status: str | None,
        parse: Callable[[Any], _RegistrantT],
        limit: int | None = None,
    ) -> list[_RegistrantT]:
        try:
            return self._paginate(
                endpoint,
                identifier,
                "registrants",
                parse,
                extra_params={"status": status} if status else None,
                limit=limit,
            )
        except requests.HTTPError as e:
            if _registration_not_enabled(e):
                return []
            raise

    def list_meeting_registrants(
        self, meeting_id: str, status: str | None = None
    ) -> list[ZoomRegistrant]:
        """Registrants belong to the scheduled meeting, not to one occurrence, so
        a recurring series returns the same list for every run."""
        return self._list_registrants(
            endpoints.MEETING_REGISTRANTS,
            meeting_id,
            status,
            ZoomRegistrant.model_validate,
        )

    def list_webinar_registrants(
        self, webinar_id: str, status: str | None = None
    ) -> list[ZoomRegistrant]:
        return self._list_registrants(
            endpoints.WEBINAR_REGISTRANTS,
            webinar_id,
            status,
            ZoomRegistrant.model_validate,
        )

    def list_webinar_panelists(self, webinar_id: str) -> list[ZoomPanelist]:
        """A panelist does not have to register, so without this a presenter is
        missing from the access list of a webinar they spoke at. Zoom takes no page
        parameters here and sends no next_page_token back, unlike the registrant and
        participant listings.
        """
        response = self._get(endpoints.WEBINAR_PANELISTS, webinar_id)
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
        endpoint = endpoints.TRANSCRIPT_DOWNLOAD
        description = endpoint.description()

        def send(token: str) -> requests.Response:
            return self._session.get(
                download_url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=REQUEST_TIMEOUT_SECONDS,
                allow_redirects=False,
            )

        response = self._send_authorized(endpoint, description, send)
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

        _raise_for_zoom_error(response, description)
        # The storage host sends no charset, so requests guesses Latin-1 and an
        # ellipsis arrives as "â€¦". WebVTT is UTF-8 by specification.
        return response.content.decode("utf-8", errors="replace")
