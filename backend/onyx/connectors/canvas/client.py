from __future__ import annotations

import re
from typing import Any

from onyx.connectors.cross_connector_utils.rate_limit_wrapper import (
    rl_requests,
)

_CANVAS_CALL_TIMEOUT = 30
_CANVAS_API_VERSION = "/api/v1"


class CanvasClientRequestFailedError(ConnectionError):
    def __init__(self, message: str, status_code: int):
        super().__init__(
            f"Canvas API request failed with status {status_code}: {message}"
        )
        self.status_code = status_code


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
        endpoint: str,
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
            url, headers=headers, params=params, timeout=_CANVAS_CALL_TIMEOUT
        )

        try:
            json = response.json()
        except Exception:
            json = {}

        if response.status_code >= 300:
            error = response.reason
            error_field = json.get("error")
            if isinstance(error_field, dict):
                response_error = error_field.get("message", "")
                if response_error:
                    error = response_error
            elif isinstance(error_field, str):
                error = error_field
            raise CanvasClientRequestFailedError(error, response.status_code)

        next_url = self._parse_next_link(response.headers.get("Link", ""))
        return json, next_url

    @staticmethod
    def _parse_next_link(link_header: str) -> str | None:
        """Extract the 'next' URL from a Canvas Link header."""
        for match in re.finditer(r'<([^>]+)>;\s*rel="next"', link_header):
            return match.group(1)
        return None

    def _build_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.bearer_token}"}

    def _build_url(self, endpoint: str) -> str:
        return f"{self.base_url}/{endpoint.lstrip('/')}"
