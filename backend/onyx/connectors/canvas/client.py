from __future__ import annotations

import logging
import re
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


class CanvasApiClient:
    def __init__(
        self,
        bearer_token: str,
        canvas_base_url: str,
    ) -> None:
        parsed_base = urlparse(canvas_base_url)
        if not parsed_base.hostname:
            raise ValueError("canvas_base_url must include a valid host")
        if parsed_base.scheme != "https":
            raise ValueError("canvas_base_url must use https")

        self._bearer_token = bearer_token
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
        headers = self._build_headers()

        response = rl_requests.get(
            url,
            headers=headers,
            params=params if not full_url else None,
            timeout=_CANVAS_CALL_TIMEOUT,
        )

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
            if parsed_url.scheme != "https":
                raise OnyxError(
                    OnyxErrorCode.BAD_GATEWAY,
                    detail=(
                        "Canvas pagination link must use https, "
                        f"got {parsed_url.scheme!r}"
                    ),
                )
            return url
        return None

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
        while response:
            yield response
            if not next_url:
                break
            response, next_url = self.get(full_url=next_url)
