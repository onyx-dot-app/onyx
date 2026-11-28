from __future__ import annotations

from collections.abc import Generator
from typing import Any

import requests
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from onyx.connectors.exceptions import SourceApiError


class JsmApiError(SourceApiError):
    def __init__(self, status_code: int, body: str) -> None:
        # SourceApiError stores status_code from its keyword argument; it must
        # be passed here, otherwise it defaults to None and the connector's
        # error mapping in validate_connector_settings never triggers.
        super().__init__(
            f"JSM API error {status_code}: {body}",
            status_code=status_code,
            body=body,
        )


class JsmApiClient:
    def __init__(self, base_url: str, email: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = Session()
        self.session.auth = requests.auth.HTTPBasicAuth(email, token)
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET"]),
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _get_paginated(
        self, url: str, params: dict[str, Any] | None = None
    ) -> Generator[dict[str, Any], None, None]:
        start = 0
        limit = 50
        while True:
            query: dict[str, Any] = {"start": start, "limit": limit}
            if params:
                query.update(params)
            response = self.session.get(url, params=query, timeout=30)
            self._check_response(response)
            data = response.json()
            yield from data.get("values", [])
            if data.get("isLastPage", True):
                break
            start += limit

    def list_service_desks(self) -> Generator[dict[str, Any], None, None]:
        url = f"{self.base_url}/rest/servicedeskapi/servicedesk"
        yield from self._get_paginated(url)

    def list_requests(
        self, service_desk_id: str | int | None = None
    ) -> Generator[dict[str, Any], None, None]:
        # The JSM API has no "all requests across all desks" endpoint, so
        # without a desk id we enumerate desks first, then each desk's requests.
        if service_desk_id is None:
            for desk in self.list_service_desks():
                desk_id = desk.get("id")
                if desk_id is None:
                    continue
                yield from self.list_requests(service_desk_id=desk_id)
            return
        url = (
            f"{self.base_url}/rest/servicedeskapi/servicedesk/{service_desk_id}/request"
        )
        yield from self._get_paginated(url)

    def get_request(self, issue_key: str) -> dict[str, Any]:
        url = f"{self.base_url}/rest/servicedeskapi/request/{issue_key}"
        response = self.session.get(url, timeout=30)
        self._check_response(response)
        return response.json()

    def list_comments(
        self, issue_key: str, public_only: bool = True
    ) -> Generator[dict[str, Any], None, None]:
        url = f"{self.base_url}/rest/servicedeskapi/request/{issue_key}/comment"
        params: dict[str, Any] = {"public": "true"} if public_only else {}
        yield from self._get_paginated(url, params=params)

    def _check_response(self, response: requests.Response) -> None:
        status = response.status_code
        if status in (401, 403, 404):
            raise JsmApiError(status, response.text)
        response.raise_for_status()
