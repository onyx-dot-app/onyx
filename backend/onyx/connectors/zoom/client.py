import time
from typing import Any
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from onyx.configs.app_configs import REQUEST_TIMEOUT_SECONDS
from onyx.connectors.exceptions import (
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.connectors.zoom.models import (
    ZoomMeetingOccurrence,
    ZoomPastMeetingDetails,
    ZoomTranscript,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

_OAUTH_TOKEN_URL = "https://zoom.us/oauth/token"
_API_BASE_URL = "https://api.zoom.us/v2"

# Zoom access tokens last about an hour. Refresh this many seconds early so a
# request never goes out holding a token that expires mid-flight.
_TOKEN_REFRESH_MARGIN_SECONDS = 60


def _encode_meeting_identifier(identifier: str) -> str:
    """Zoom's docs require encoding a UUID twice when it starts with "/" or
    contains "//", because something in front of their API decodes one layer
    before the request arrives."""
    encoded = quote(identifier, safe="")
    if identifier.startswith("/") or "//" in identifier:
        encoded = quote(encoded, safe="")
    return encoded


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
        self._session.mount(_API_BASE_URL, HTTPAdapter(max_retries=retry_strategy))

    def _fetch_access_token(self) -> None:
        response = requests.post(
            _OAUTH_TOKEN_URL,
            params={
                "grant_type": "account_credentials",
                "account_id": self.account_id,
            },
            auth=(self.client_id, self.client_secret),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code == 401:
            raise CredentialExpiredError(
                "Zoom rejected the Server-to-Server OAuth client credentials"
            )
        response.raise_for_status()

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

    def _request(self, method: str, endpoint: str, **kwargs: Any) -> requests.Response:
        url = f"{_API_BASE_URL}{endpoint}"
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self._get_access_token()}"

        response = self._session.request(
            method, url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS, **kwargs
        )

        if response.status_code == 401:
            raise CredentialExpiredError("Zoom rejected the request as unauthorized")
        if response.status_code == 403:
            raise InsufficientPermissionsError(
                f"Zoom denied access to {endpoint} — check the app's granted scopes"
            )

        return response

    def get_meeting_transcript(self, meeting_identifier: str) -> ZoomTranscript | None:
        """This endpoint takes a meeting ID, a webinar ID, or a single
        occurrence's UUID. None means Zoom has no recording for it, so the
        caller should skip it rather than treat it as an error."""
        response = self._request(
            "GET",
            f"/meetings/{_encode_meeting_identifier(meeting_identifier)}/transcript",
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return ZoomTranscript.model_validate(response.json())

    def get_past_meeting_details(
        self, meeting_identifier: str
    ) -> ZoomPastMeetingDetails | None:
        response = self._request(
            "GET", f"/past_meetings/{_encode_meeting_identifier(meeting_identifier)}"
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return ZoomPastMeetingDetails.model_validate(response.json())

    def list_past_meeting_occurrences(
        self, meeting_id: str
    ) -> list[ZoomMeetingOccurrence]:
        """A recurring meeting records each run separately, and passing the
        bare meeting_id to the transcript endpoint only ever reaches the
        latest one. Call this first to get every past occurrence's UUID."""
        response = self._request(
            "GET",
            f"/past_meetings/{_encode_meeting_identifier(meeting_id)}/instances",
        )
        if response.status_code == 404:
            return []
        response.raise_for_status()
        occurrences = response.json().get("meetings", [])
        return [ZoomMeetingOccurrence.model_validate(o) for o in occurrences]

    def download_transcript_vtt(self, download_url: str) -> str:
        response = requests.get(
            download_url,
            headers={"Authorization": f"Bearer {self._get_access_token()}"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.text
