import time
from collections.abc import Callable
from typing import Any
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
    ZoomMeetingOccurrence,
    ZoomPastMeetingDetails,
    ZoomTranscript,
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


def _encode_meeting_identifier(identifier: str) -> str:
    """Zoom requires a UUID to be encoded twice when it starts with "/" or
    contains "//"."""
    encoded = quote(identifier, safe="")
    if identifier.startswith("/") or "//" in identifier:
        encoded = quote(encoded, safe="")
    return encoded


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

    def _fetch_access_token(self) -> None:
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

        token_data = response.json()
        self._access_token = token_data["access_token"]
        expires_in = token_data.get("expires_in", 3600)
        self._token_expires_at = time.monotonic() + expires_in

    def _get_access_token(self) -> str:
        if (
            self._access_token is None
            or time.monotonic()
            >= self._token_expires_at - _TOKEN_REFRESH_MARGIN_SECONDS
        ):
            self._fetch_access_token()
        assert self._access_token is not None
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

    def get_meeting_transcript(self, meeting_identifier: str) -> ZoomTranscript | None:
        """Takes a meeting ID, a webinar ID, or one occurrence's UUID. Zoom has
        no webinar transcript endpoint, so webinars come through here too.
        Returns None when the session was never recorded, which is a normal skip.
        """
        response = self._request(
            "GET",
            f"/meetings/{_encode_meeting_identifier(meeting_identifier)}/transcript",
        )
        if response.status_code == 404:
            return None
        _raise_for_zoom_error(response, f"the transcript for {meeting_identifier}")
        return ZoomTranscript.model_validate(response.json())

    def get_past_meeting_details(
        self, meeting_identifier: str
    ) -> ZoomPastMeetingDetails | None:
        response = self._request(
            "GET", f"/past_meetings/{_encode_meeting_identifier(meeting_identifier)}"
        )
        if response.status_code == 404:
            return None
        _raise_for_zoom_error(response, f"the details for {meeting_identifier}")
        return ZoomPastMeetingDetails.model_validate(response.json())

    def list_past_meeting_occurrences(
        self, meeting_id: str
    ) -> list[ZoomMeetingOccurrence]:
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
        if response.status_code == 404:
            return []
        _raise_for_zoom_error(response, f"the occurrences for {meeting_id}")
        occurrences = response.json().get("meetings", [])
        return [ZoomMeetingOccurrence.model_validate(o) for o in occurrences]

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
