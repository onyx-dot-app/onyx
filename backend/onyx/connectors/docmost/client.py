"""Thin HTTP client for the DocMost API.

DocMost API conventions (verified against https://docmost.com/api-docs):
  - Base URL is the instance origin; all API paths are under ``{origin}/api``.
  - Almost every endpoint is POST (a handful of file/health endpoints are GET).
  - Auth is a bearer token: ``Authorization: Bearer <token>``.
  - Successful responses are wrapped as ``{"data": ..., "success": true, "status": 200}``.
  - List endpoints use cursor pagination. The request takes ``{"limit": 1-100, "cursor": <opaque>}``
    and the response ``data`` is ``{"items": [...], "meta": {"hasNextPage", "nextCursor", ...}}``.

Response/record field names are verified against a live DocMost instance and are
isolated in DocmostConnector, not here. /pages/recent returns page metadata only
(no `content` body); the connector fetches full content per-page via /pages/info.
"""

import time
from typing import Any

import requests

from onyx.utils.logger import setup_logger

logger = setup_logger()

# DocMost pagination cap (limit must be 1..100; default 20).
MAX_PAGE_LIMIT = 100

# Conservative retry policy for 429 / 5xx.
_MAX_RETRIES = 5
_BACKOFF_BASE_SECONDS = 1.0
_REQUEST_TIMEOUT_SECONDS = 60


class DocmostClientError(Exception):
    """Base error for DocMost client failures."""


class DocmostAuthError(DocmostClientError):
    """401/403 — bad token or insufficient permissions for the service user."""


class DocmostClient:
    def __init__(self, base_url: str, api_token: str) -> None:
        # Normalize: strip trailing slashes, ensure a single /api suffix.
        origin = base_url.rstrip("/")
        if origin.endswith("/api"):
            origin = origin[: -len("/api")]
        self._api_base = f"{origin}/api"

        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

    def _post(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        """POST to an API path and return the unwrapped ``data`` field.

        Retries on 429 and 5xx with exponential backoff. Maps auth failures
        to DocmostAuthError so the connector can surface a clear message.
        """
        url = f"{self._api_base}/{path.lstrip('/')}"
        body = payload or {}

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                resp = self._session.post(
                    url, json=body, timeout=_REQUEST_TIMEOUT_SECONDS
                )
            except requests.RequestException as e:
                last_exc = e
                self._sleep_backoff(attempt)
                continue

            if resp.status_code in (401, 403):
                raise DocmostAuthError(
                    f"DocMost returned {resp.status_code} for {path}. "
                    "Check the API token and that the service user has access "
                    "to the requested spaces."
                )

            if resp.status_code == 429 or resp.status_code >= 500:
                retry_after = resp.headers.get("Retry-After")
                wait = (
                    float(retry_after)
                    if retry_after and retry_after.isdigit()
                    else _BACKOFF_BASE_SECONDS * (2**attempt)
                )
                logger.warning(
                    f"DocMost {resp.status_code} on {path}; "
                    f"retry {attempt + 1}/{_MAX_RETRIES} after {wait:.1f}s"
                )
                time.sleep(wait)
                continue

            if not resp.ok:
                raise DocmostClientError(
                    f"DocMost request to {path} failed with "
                    f"{resp.status_code}: {resp.text[:500]}"
                )

            parsed = resp.json()
            # Envelope is {data, success, status}; tolerate a bare body too.
            if isinstance(parsed, dict) and "data" in parsed:
                return parsed["data"]
            return parsed

        raise DocmostClientError(
            f"DocMost request to {path} exhausted retries"
            + (f": {last_exc}" if last_exc else "")
        )

    @staticmethod
    def _sleep_backoff(attempt: int) -> None:
        time.sleep(_BACKOFF_BASE_SECONDS * (2**attempt))

    def post(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        """Public single-shot POST returning the unwrapped ``data``."""
        return self._post(path, payload)

    def paginate(
        self,
        path: str,
        payload: dict[str, Any] | None = None,
        limit: int = MAX_PAGE_LIMIT,
    ) -> Any:
        """Yield items across all pages of a cursor-paginated list endpoint.

        Reads ``data.items`` and follows ``data.meta.nextCursor`` until
        ``hasNextPage`` is false. Yields individual item dicts.
        """
        base_payload = dict(payload or {})
        base_payload["limit"] = max(1, min(limit, MAX_PAGE_LIMIT))
        cursor: str | None = None

        while True:
            req = dict(base_payload)
            if cursor:
                req["cursor"] = cursor

            data = self._post(path, req)

            # Defensive: list endpoints nest under items; tolerate a bare list.
            if isinstance(data, dict):
                items = data.get("items", [])
                meta = data.get("meta", {}) or {}
            elif isinstance(data, list):
                items = data
                meta = {}
            else:
                items = []
                meta = {}

            for item in items:
                yield item

            if not meta.get("hasNextPage"):
                break
            cursor = meta.get("nextCursor")
            if not cursor:
                break
