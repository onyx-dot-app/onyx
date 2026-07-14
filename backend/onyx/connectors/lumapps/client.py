import base64
import time
from typing import Any

import requests

from onyx.utils.logger import setup_logger

logger = setup_logger()

# The documented public API lives under the legacy lumsites path on the customer cell.
LEGACY_PREFIX = "/_ah/api/lumsites/v1"

_MAX_RETRIES = 5
_MAX_BACKOFF_SECONDS = 60.0
_TOKEN_REFRESH_SKEW_SECONDS = 60  # mint a new token this long before it expires


class LumAppsClientError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"LumApps API error {status_code}: {message}")
        self.status_code = status_code
        self.message = message


def _backoff_seconds(response: requests.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return min(max(float(retry_after), 1.0), _MAX_BACKOFF_SECONDS)
        except ValueError:
            pass
    return min(2.0**attempt, _MAX_BACKOFF_SECONDS)


class OnyxLumApps:
    """Thin LumApps API client.

    Auth (verified live): exchange the application id + api key (HTTP Basic) for a
    short-lived JWT via ``application-token`` (``grant_type=client_credentials``,
    on-behalf-of a service user), then call the data endpoints with just
    ``Authorization: Bearer <jwt>`` — the token carries the organization, so no other
    headers are required. The JWT (~1 h) is cached and re-minted before it expires.
    """

    def __init__(
        self,
        base_url: str,
        organization_id: str,
        application_id: str,
        api_key: str,
        service_user: str,
        timeout: int = 60,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.organization_id = organization_id
        self.application_id = application_id
        self.api_key = api_key
        self.service_user = service_user
        self.timeout = timeout
        self._session = requests.Session()
        self._token: str | None = None
        self._token_expiry_monotonic: float = 0.0

    # ------------------------------------------------------------------ auth
    def _basic_header(self) -> str:
        raw = f"{self.application_id}:{self.api_key}".encode()
        return "Basic " + base64.b64encode(raw).decode()

    def _mint_token(self) -> None:
        url = (
            f"{self.base_url}/v2/organizations/{self.organization_id}/application-token"
        )
        data: dict[str, str] = {"grant_type": "client_credentials"}
        if "@" in (self.service_user or ""):
            data["user_email"] = self.service_user
        elif self.service_user:
            data["user_id"] = self.service_user

        response = self._session.post(
            url,
            headers={
                "Authorization": self._basic_header(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=data,
            timeout=self.timeout,
        )
        if response.status_code != 200:
            raise LumAppsClientError(response.status_code, response.text)
        body = response.json()
        self._token = body["access_token"]
        expires_in = int(body.get("expires_in", 3600))
        self._token_expiry_monotonic = (
            time.monotonic() + max(expires_in, 120) - _TOKEN_REFRESH_SKEW_SECONDS
        )

    def _bearer(self) -> str:
        if not self._token or time.monotonic() >= self._token_expiry_monotonic:
            self._mint_token()
        assert self._token is not None
        return self._token

    # --------------------------------------------------------------- request
    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        last_network_error: requests.RequestException | None = None
        last_http_status: int | None = None
        last_http_text: str = ""
        for attempt in range(_MAX_RETRIES):
            try:
                response = self._session.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers={
                        "Authorization": f"Bearer {self._bearer()}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    timeout=self.timeout,
                )
            except requests.RequestException as e:
                # Connection resets / timeouts are as transient as a 5xx —
                # back off and retry instead of aborting the indexing attempt.
                last_network_error = e
                delay = min(2.0**attempt, _MAX_BACKOFF_SECONDS)
                logger.warning(
                    "LumApps network error on %s (%s); retry %d in %.1fs",
                    path,
                    e,
                    attempt + 1,
                    delay,
                )
                time.sleep(delay)
                continue
            if response.status_code == 401 and attempt == 0:
                self._token = None  # expired/invalid; next _bearer() re-mints
                continue
            if response.status_code == 429 or response.status_code >= 500:
                last_http_status = response.status_code
                last_http_text = response.text
                delay = _backoff_seconds(response, attempt)
                logger.warning(
                    "LumApps %s on %s; retry %d in %.1fs",
                    response.status_code,
                    path,
                    attempt + 1,
                    delay,
                )
                time.sleep(delay)
                continue
            if response.status_code != 200:
                raise LumAppsClientError(response.status_code, response.text)
            return response.json()
        # Surface the real upstream status (429/5xx) when the last failure was an
        # HTTP error, so callers (validation included) can translate it; fall back
        # to 503 only for pure network exhaustion.
        if last_http_status is not None:
            raise LumAppsClientError(
                last_http_status, f"Exhausted retries calling {path}: {last_http_text}"
            )
        detail = f": {last_network_error}" if last_network_error else ""
        raise LumAppsClientError(503, f"Exhausted retries calling {path}{detail}")

    # ---------------------------------------------------------------- methods
    def list_content(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"{LEGACY_PREFIX}/content/list", json_body=body)

    def get_content(self, uid: str, lang: str) -> dict[str, Any]:
        return self._request(
            "GET", f"{LEGACY_PREFIX}/content/get", params={"uid": uid, "lang": lang}
        )

    def get_metadata(self, uid: str, lang: str) -> dict[str, Any]:
        return self._request(
            "GET", f"{LEGACY_PREFIX}/metadata/get", params={"uid": uid, "lang": lang}
        )
