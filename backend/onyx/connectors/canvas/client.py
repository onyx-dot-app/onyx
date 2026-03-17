from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from onyx.connectors.cross_connector_utils.rate_limit_wrapper import (
    rl_requests,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

_CANVAS_CALL_TIMEOUT = 30
_CANVAS_API_VERSION = "/api/v1"


class CanvasApiClient:
    def __init__(
        self,
        bearer_token: str,
        canvas_base_url: str,
    ) -> None:
        self.bearer_token = bearer_token
        self.base_url = canvas_base_url.rstrip("/") + _CANVAS_API_VERSION

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
        """
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
        except Exception as e:
            if response.status_code < 300:
                raise OnyxError(
                    OnyxErrorCode.BAD_GATEWAY,
                    detail=f"Invalid JSON in Canvas response: {e}",
                )
            response_json = {}

        if response.status_code >= 300:
            error = response.reason
            error_field = response_json.get("error")
            if isinstance(error_field, dict):
                response_error = error_field.get("message", "")
                if response_error:
                    error = response_error
            elif isinstance(error_field, str):
                error = error_field
            # Canvas also returns {"errors": [{"message": "..."}]} for many endpoints
            errors_list = response_json.get("errors")
            if isinstance(errors_list, list) and errors_list:
                first_error = errors_list[0]
                if isinstance(first_error, dict):
                    msg = first_error.get("message", "")
                    if msg:
                        error = msg
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
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
        expected_host = urlparse(self.base_url).hostname
        for match in re.finditer(r'<([^>]+)>;\s*rel="next"', link_header):
            url = match.group(1)
            if urlparse(url).hostname == expected_host:
                return url
        return None

    def _build_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.bearer_token}"}

    def _build_url(self, endpoint: str) -> str:
        return f"{self.base_url}/{endpoint.lstrip('/')}"
