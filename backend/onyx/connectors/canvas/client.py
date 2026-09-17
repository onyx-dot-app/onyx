from __future__ import annotations

import logging
import re
from collections.abc import Callable
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlparse

from onyx.connectors.cross_connector_utils.rate_limit_wrapper import (
    rl_requests,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

logger = logging.getLogger(__name__)

# Requests timeout in seconds.
_CANVAS_CALL_TIMEOUT: int = 30
# Files are streamed in chunks of this size so an oversized download can be
# abandoned before it is fully buffered.
_DOWNLOAD_CHUNK_SIZE: int = 64 * 1024
_CANVAS_API_VERSION: str = "/api/v1"
# Matches the "next" URL in a Canvas Link header, e.g.:
#   <https://canvas.example.com/api/v1/courses?page=2>; rel="next"
# Captures the URL inside the angle brackets.
_NEXT_LINK_PATTERN: re.Pattern[str] = re.compile(r'<([^>]+)>;\s*rel="next"')


_STATUS_TO_ERROR_CODE: dict[int, OnyxErrorCode] = {
    401: OnyxErrorCode.CREDENTIAL_EXPIRED,
    403: OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
    404: OnyxErrorCode.BAD_GATEWAY,
    429: OnyxErrorCode.RATE_LIMITED,
}


def _error_code_for_status(status_code: int) -> OnyxErrorCode:
    """Map an HTTP status code to the appropriate OnyxErrorCode.

    Expects a >= 400 status code. Known codes (401, 403, 404, 429) are
    mapped to specific error codes; all other codes (unrecognised 4xx
    and 5xx) map to BAD_GATEWAY as unexpected upstream errors.
    """
    if status_code in _STATUS_TO_ERROR_CODE:
        return _STATUS_TO_ERROR_CODE[status_code]
    return OnyxErrorCode.BAD_GATEWAY


def _is_canvas_login_url(url: str) -> bool:
    """True for Canvas's login page (``/login`` or ``/login/<provider>``)."""
    path = urlparse(url).path.rstrip("/")
    return path == "/login" or path.startswith("/login/")


# Called when Canvas answers 401. Returns a fresh bearer token to retry with,
# or None if no refresh is possible (static token / refresh failed).
TokenRefresher = Callable[[], str | None]


class CanvasApiClient:
    def __init__(
        self,
        bearer_token: str,
        canvas_base_url: str,
        token_refresher: TokenRefresher | None = None,
    ) -> None:
        parsed_base = urlparse(canvas_base_url)
        if not parsed_base.hostname:
            raise ValueError("canvas_base_url must include a valid host")
        # if parsed_base.scheme != "https":
        #     raise ValueError("canvas_base_url must use https")

        self._bearer_token = bearer_token
        self._token_refresher = token_refresher
        self.base_url = (
            canvas_base_url.rstrip("/").removesuffix(_CANVAS_API_VERSION)
            + _CANVAS_API_VERSION
        )
        # Hostname is already validated above; reuse parsed_base instead
        # of re-parsing.  Used by _parse_next_link to validate pagination URLs.
        self._expected_host: str = parsed_base.hostname

    def get(
        self,
        endpoint: str = "",
        params: dict[str, Any] | None = None,
        full_url: str | None = None,
    ) -> tuple[Any, str | None]:
        """Make a GET request to the Canvas API.

        Returns a tuple of (json_body, next_url).
        next_url is parsed from the Link header and is None if there are no more pages.
        If full_url is provided, it is used directly (for following pagination links).

        Security note: full_url must only be set to values returned by
        ``_parse_next_link``, which validates the host against the configured
        Canvas base URL.  Passing an arbitrary URL would leak the bearer token.
        """
        # full_url is used when following pagination (Canvas returns the
        # next-page URL in the Link header).  For the first request we build
        # the URL from the endpoint name instead.
        url = full_url if full_url else self._build_url(endpoint)
        response = self._request(url, params if not full_url else None)

        # OAuth access tokens expire hourly. On a 401, ask the refresher for a
        # new token and retry exactly once; static tokens have no refresher.
        if response.status_code == 401 and self._token_refresher is not None:
            refreshed_token = self._token_refresher()
            if refreshed_token and refreshed_token != self._bearer_token:
                self._bearer_token = refreshed_token
                response = self._request(url, params if not full_url else None)

        try:
            response_json = response.json()
        except ValueError as e:
            if response.status_code < 300:
                raise OnyxError(
                    OnyxErrorCode.BAD_GATEWAY,
                    detail=f"Invalid JSON in Canvas response: {e}",
                )
            logger.warning(
                "Failed to parse JSON from Canvas error response (status=%d): %s",
                response.status_code,
                e,
            )
            response_json = {}

        if response.status_code >= 400:
            # Try to extract the most specific error message from the
            # Canvas response body.  Canvas uses three different shapes
            # depending on the endpoint and error type:
            default_error: str = response.reason or f"HTTP {response.status_code}"
            error = default_error
            if isinstance(response_json, dict):
                # Shape 1: {"error": {"message": "Not authorized"}}
                error_field = response_json.get("error")
                if isinstance(error_field, dict):
                    response_error = error_field.get("message", "")
                    if response_error:
                        error = response_error
                # Shape 2: {"error": "Invalid access token"}
                elif isinstance(error_field, str):
                    error = error_field
                # Shape 3: {"errors": [{"message": "..."}]}
                # Used for validation errors.  Only use as fallback if
                # we didn't already find a more specific message above.
                if error == default_error:
                    errors_list = response_json.get("errors")
                    if isinstance(errors_list, list) and errors_list:
                        first_error = errors_list[0]
                        if isinstance(first_error, dict):
                            msg = first_error.get("message", "")
                            if msg:
                                error = msg
            raise OnyxError(
                _error_code_for_status(response.status_code),
                detail=error,
                status_code_override=response.status_code,
            )

        next_url = self._parse_next_link(response.headers.get("Link", ""))
        return response_json, next_url

    def get_file_public_url(self, file_id: int) -> str | None:
        """Ask Canvas for a self-authorizing download URL for a file.

        ``GET /api/v1/files/:id/public_url`` returns a signed URL (S3 /
        inst-fs) or, for local storage, a download URL carrying a
        ``verifier``. Requires the ``url:GET|/api/v1/files/:id/public_url``
        scope on developer keys that enforce scopes.
        """
        body, _ = self.get(f"files/{file_id}/public_url")
        if not isinstance(body, dict):
            return None
        public_url = body.get("public_url")
        return public_url if isinstance(public_url, str) and public_url else None

    def download_file(self, url: str, max_bytes: int | None = None) -> bytes:
        """Download a file's raw bytes from a self-authorizing Canvas URL.

        ``url`` must carry its own authorization: a file ``url`` that includes
        a ``verifier`` query parameter, or the signed URL returned by
        ``get_file_public_url``. No Authorization header is sent: Canvas
        rejects bearer tokens on the non-API ``/files/:id/download`` route
        with 401 when the developer key enforces scopes, and omitting it also
        keeps the token away from storage hosts the download redirects to.

        When Canvas will not serve the file it redirects to its login page
        with a 200, so that is detected and reported as a failure rather than
        indexing the login page's HTML.

        The body is streamed. When ``max_bytes`` is given, the download is
        abandoned as soon as it is known to exceed that size (from
        ``Content-Length`` or while reading), so a file whose advertised
        ``size`` is missing or wrong cannot buffer unbounded data in memory.
        """
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                detail=f"Invalid Canvas file download URL: {url!r}",
            )

        response = rl_requests.get(
            url,
            timeout=_CANVAS_CALL_TIMEOUT,
            allow_redirects=True,
            stream=True,
        )
        try:
            if response.status_code >= 400:
                raise OnyxError(
                    _error_code_for_status(response.status_code),
                    detail=(
                        f"Failed to download Canvas file: "
                        f"{response.reason or f'HTTP {response.status_code}'}"
                    ),
                    status_code_override=response.status_code,
                )

            visited = [r.url for r in response.history] + [response.url]
            if any(_is_canvas_login_url(visited_url) for visited_url in visited):
                raise OnyxError(
                    OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                    detail=(
                        "Canvas redirected the file download to its login page; "
                        "the download URL is not authorized"
                    ),
                )

            if max_bytes is not None:
                content_length = response.headers.get("Content-Length")
                if (
                    isinstance(content_length, str)
                    and content_length.isdigit()
                    and int(content_length) > max_bytes
                ):
                    raise OnyxError(
                        OnyxErrorCode.PAYLOAD_TOO_LARGE,
                        detail=(
                            f"Canvas file is {content_length} bytes, over the "
                            f"{max_bytes} byte limit"
                        ),
                    )

            buffer = bytearray()
            for chunk in response.iter_content(chunk_size=_DOWNLOAD_CHUNK_SIZE):
                if not chunk:
                    continue
                buffer.extend(chunk)
                if max_bytes is not None and len(buffer) > max_bytes:
                    raise OnyxError(
                        OnyxErrorCode.PAYLOAD_TOO_LARGE,
                        detail=(
                            f"Canvas file download exceeded the {max_bytes} "
                            "byte limit"
                        ),
                    )
            return bytes(buffer)
        finally:
            response.close()

    def _parse_next_link(self, link_header: str) -> str | None:
        """Extract the 'next' URL from a Canvas Link header.

        Only returns URLs whose host matches the configured Canvas base URL
        to prevent leaking the bearer token to arbitrary hosts.
        """
        expected_host = self._expected_host
        for match in _NEXT_LINK_PATTERN.finditer(link_header):
            url = match.group(1)
            parsed_url = urlparse(url)
            if parsed_url.hostname != expected_host:
                raise OnyxError(
                    OnyxErrorCode.BAD_GATEWAY,
                    detail=(
                        "Canvas pagination returned an unexpected host "
                        f"({parsed_url.hostname}); expected {expected_host}"
                    ),
                )
            # if parsed_url.scheme != "https":
            #     raise OnyxError(
            #         OnyxErrorCode.BAD_GATEWAY,
            #         detail=(
            #             "Canvas pagination link must use https, "
            #             f"got {parsed_url.scheme!r}"
            #         ),
            #     )
            return url
        return None

    def _request(self, url: str, params: dict[str, Any] | None) -> Any:
        return rl_requests.get(
            url,
            headers=self._build_headers(),
            params=params,
            timeout=_CANVAS_CALL_TIMEOUT,
        )

    @property
    def bearer_token(self) -> str:
        return self._bearer_token

    def _build_headers(self) -> dict[str, str]:
        """Return the Authorization header with the bearer token."""
        return {"Authorization": f"Bearer {self._bearer_token}"}

    def _build_url(self, endpoint: str) -> str:
        """Build a full Canvas API URL from an endpoint path.

        Assumes endpoint is non-empty (e.g. ``"courses"``, ``"announcements"``).
        Only called on a first request, endpoint must be set for first request.
        Verify endpoint exists in case of future changes where endpoint might be optional.
        Leading slashes are stripped to avoid double-slash in the result.
        self.base_url is already normalized with no trailing slash.
        """
        final_url = self.base_url
        clean_endpoint = endpoint.lstrip("/")
        if clean_endpoint:
            final_url += "/" + clean_endpoint
        return final_url

    def paginate(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> Iterator[list[Any]]:
        """Yield each page of results, following Link-header pagination.

        Makes the first request with endpoint + params, then follows
        next_url from Link headers for subsequent pages.
        """
        response, next_url = self.get(endpoint, params=params)
        while True:
            if not response:
                break
            yield response
            if not next_url:
                break
            response, next_url = self.get(full_url=next_url)
