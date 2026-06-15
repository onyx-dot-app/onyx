from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

import requests

from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.tools.tool_implementations.web_search.models import WebSearchMode
from onyx.tools.tool_implementations.web_search.models import WebSearchProvider
from onyx.tools.tool_implementations.web_search.models import WebSearchResult
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()

GLOMI_SEARCH_PATH = "/search"
GLOMI_SEARCH_LOCALE = "zh-CN"
GLOMI_SEARCH_TIMEOUT_SECONDS = 15


class RetryableGlomiSearchError(Exception):
    """Error type used to retry transient Glomi Search Gateway failures."""


class GlomiSearchClient(WebSearchProvider):
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str,
        channel: str | None = None,
        num_results: int = 20,
        timeout_seconds: int = GLOMI_SEARCH_TIMEOUT_SECONDS,
    ) -> None:
        if not base_url.strip():
            raise ValueError("Glomi Search provider config 'base_url' is required.")
        if timeout_seconds <= 0:
            raise ValueError(
                "Glomi Search provider config 'timeout_seconds' must be greater than 0."
            )

        self._base_url = base_url.strip().rstrip("/")
        self._channel = channel.strip() if channel and channel.strip() else None
        self._num_results = max(1, num_results)
        self._timeout_seconds = timeout_seconds
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    @property
    def supports_batch_queries(self) -> bool:
        return True

    def search(self, query: str) -> list[WebSearchResult]:
        return list(self.search_batch([query], mode=WebSearchMode.LITE))

    def search_batch(
        self,
        queries: Sequence[str],
        *,
        mode: WebSearchMode = WebSearchMode.LITE,
        max_results: int | None = None,
    ) -> list[WebSearchResult]:
        try:
            return self._search_batch_with_retries(
                list(queries),
                mode=mode,
                max_results=max_results,
            )
        except RetryableGlomiSearchError as exc:
            raise ValueError(str(exc)) from exc

    @retry_builder(
        tries=3,
        delay=1,
        backoff=2,
        exceptions=(RetryableGlomiSearchError,),
    )
    def _search_batch_with_retries(
        self,
        queries: list[str],
        *,
        mode: WebSearchMode,
        max_results: int | None,
    ) -> list[WebSearchResult]:
        payload: dict[str, Any] = {
            "queries": queries,
            "mode": mode.value,
            "max_results": max_results or self._num_results,
            "locale": GLOMI_SEARCH_LOCALE,
        }
        if self._channel:
            payload["channel"] = self._channel

        try:
            response = requests.post(
                f"{self._base_url}{GLOMI_SEARCH_PATH}",
                headers=self._headers,
                json=payload,
                timeout=self._timeout_seconds,
            )
        except requests.RequestException as exc:
            raise RetryableGlomiSearchError(
                f"Glomi Search provider failed: {exc}"
            ) from exc

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            error_message = _build_error_message(response)
            if response.status_code in {401, 403}:
                raise ValueError("Invalid Glomi Search API key") from exc
            if response.status_code == 429:
                raise ValueError("Glomi Search rate limit exceeded") from exc
            if response.status_code >= 500:
                raise RetryableGlomiSearchError(error_message) from exc
            raise ValueError(error_message) from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise ValueError("Glomi Search provider failed: non-JSON response") from exc

        raw_results = data.get("results")
        if not isinstance(raw_results, list):
            raise ValueError("Glomi Search provider failed: missing results list")

        results: list[WebSearchResult] = []
        for raw_result in raw_results:
            if not isinstance(raw_result, dict):
                continue

            link = _clean_string(raw_result.get("url") or raw_result.get("link"))
            if not link:
                continue

            results.append(
                WebSearchResult(
                    title=_clean_string(raw_result.get("title")),
                    link=link,
                    snippet=_clean_string(raw_result.get("snippet")),
                    author=_optional_clean_string(raw_result.get("author")),
                    published_date=_parse_published_date(
                        raw_result.get("published_date")
                    ),
                )
            )

        return results

    def test_connection(self) -> dict[str, str]:
        try:
            test_results = self.search("test")
            if not test_results or not any(result.link for result in test_results):
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    "Glomi Search validation failed: search returned no results.",
                )
        except OnyxError:
            raise
        except ValueError as exc:
            error_message = str(exc)
            if "Invalid Glomi Search API key" in error_message:
                raise OnyxError(OnyxErrorCode.INVALID_INPUT, error_message) from exc
            if "rate limit" in error_message.lower():
                raise OnyxError(OnyxErrorCode.INVALID_INPUT, error_message) from exc
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"Glomi Search validation failed: {error_message}",
            ) from exc

        logger.info("Web search provider test succeeded for Glomi Search.")
        return {"status": "ok"}


def _build_error_message(response: requests.Response) -> str:
    return (
        f"Glomi Search provider failed (status {response.status_code}): "
        f"{_extract_error_detail(response)}"
    )


def _extract_error_detail(response: requests.Response) -> str:
    try:
        payload: Any = response.json()
    except Exception:
        text = response.text.strip()
        return text[:200] if text else "No error details"

    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("message") or payload.get("error")
        if isinstance(detail, str):
            return detail

    return str(payload)[:200]


def _clean_string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _optional_clean_string(value: Any) -> str | None:
    cleaned = _clean_string(value)
    return cleaned or None


def _parse_published_date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return time_str_to_utc(value)
    except Exception:
        return None
