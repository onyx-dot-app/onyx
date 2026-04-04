from __future__ import annotations

from datetime import datetime
from typing import Any

import requests
from fastapi import HTTPException

from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.tools.tool_implementations.web_search.models import (
    WebSearchProvider,
)
from onyx.tools.tool_implementations.web_search.models import WebSearchResult
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()

BAIDU_WEB_SEARCH_URL = "https://qianfan.baidubce.com/v2/ai_search/web_search"
BAIDU_MAX_RESULTS_PER_REQUEST = 50
BAIDU_DEFAULT_SEARCH_SOURCE = "baidu_search_v2"


class RetryableBaiduSearchError(Exception):
    """Error type used to trigger retry for transient Baidu search failures."""


class BaiduClient(WebSearchProvider):
    def __init__(
        self,
        api_key: str,
        *,
        num_results: int = 10,
        timeout_seconds: int = 10,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Baidu provider config 'timeout_seconds' must be > 0.")

        bearer_token = f"Bearer {api_key}"
        self._headers = {
            "Authorization": bearer_token,
            "X-Appbuilder-Authorization": bearer_token,
            "Content-Type": "application/json",
        }
        self._num_results = max(1, min(num_results, BAIDU_MAX_RESULTS_PER_REQUEST))
        self._timeout_seconds = timeout_seconds

    def _build_payload(self, query: str) -> dict[str, Any]:
        return {
            "messages": [
                {
                    "role": "user",
                    "content": query,
                }
            ],
            "search_source": BAIDU_DEFAULT_SEARCH_SOURCE,
            "resource_type_filter": [{"type": "web", "top_k": self._num_results}],
        }

    @retry_builder(
        tries=3,
        delay=1,
        backoff=2,
        exceptions=(RetryableBaiduSearchError,),
    )
    def _search_with_retries(self, query: str) -> list[WebSearchResult]:
        payload = self._build_payload(query)

        try:
            response = requests.post(
                BAIDU_WEB_SEARCH_URL,
                headers=self._headers,
                json=payload,
                timeout=self._timeout_seconds,
            )
        except requests.RequestException as exc:
            raise RetryableBaiduSearchError(
                f"Baidu search request failed: {exc}"
            ) from exc

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            error_msg = _build_error_message(response)
            if _is_retryable_status(response.status_code):
                raise RetryableBaiduSearchError(error_msg) from exc
            raise ValueError(error_msg) from exc

        data = response.json()
        api_code = data.get("code")
        if api_code is not None and str(api_code) != "0":
            api_message = _clean_string(data.get("message")) or "Unknown error"
            raise ValueError(f"Baidu search failed (code {api_code}): {api_message}")

        references = data.get("references") or []
        if isinstance(references, dict):
            references = [references]
        if not isinstance(references, list):
            references = []

        results: list[WebSearchResult] = []
        for reference in references:
            if not isinstance(reference, dict):
                continue

            resource_type = _clean_string(reference.get("type")).lower()
            if resource_type and resource_type != "web":
                continue

            link = _clean_string(reference.get("url"))
            if not link:
                continue

            title = _clean_string(reference.get("title")) or _clean_string(
                reference.get("web_anchor")
            )
            snippet = _clean_string(reference.get("snippet")) or _clean_string(
                reference.get("content")
            )

            results.append(
                WebSearchResult(
                    title=title,
                    link=link,
                    snippet=snippet,
                    author=_optional_clean_string(reference.get("website")),
                    published_date=_parse_published_date(reference.get("date")),
                )
            )

        return results

    def search(self, query: str) -> list[WebSearchResult]:
        try:
            return self._search_with_retries(query)
        except RetryableBaiduSearchError as exc:
            raise ValueError(str(exc)) from exc

    def test_connection(self) -> dict[str, str]:
        try:
            test_results = self.search("test")
            if not test_results or not any(result.link for result in test_results):
                raise HTTPException(
                    status_code=400,
                    detail="Baidu API key validation failed: search returned no results.",
                )
        except HTTPException:
            raise
        except (ValueError, requests.RequestException) as e:
            error_msg = str(e)
            lower = error_msg.lower()
            if (
                "status 401" in lower
                or "status 403" in lower
                or "api key" in lower
                or "auth" in lower
            ):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid Baidu API key: {error_msg}",
                ) from e
            if "status 429" in lower or "rate limit" in lower:
                raise HTTPException(
                    status_code=400,
                    detail=f"Baidu API rate limit exceeded: {error_msg}",
                ) from e
            raise HTTPException(
                status_code=400,
                detail=f"Baidu API key validation failed: {error_msg}",
            ) from e

        logger.info("Web search provider test succeeded for Baidu.")
        return {"status": "ok"}


def _build_error_message(response: requests.Response) -> str:
    return f"Baidu search failed (status {response.status_code}): {_extract_error_detail(response)}"


def _extract_error_detail(response: requests.Response) -> str:
    try:
        payload: Any = response.json()
    except Exception:
        text = response.text.strip()
        return text[:200] if text else "No error details"

    if isinstance(payload, dict):
        code = payload.get("code")
        message = payload.get("message")
        if code is not None and isinstance(message, str):
            return f"{code}: {message}"
        if isinstance(message, str):
            return message

        error = payload.get("error")
        if isinstance(error, dict):
            detail = error.get("detail") or error.get("message")
            if isinstance(detail, str):
                return detail
        if isinstance(error, str):
            return error

    return str(payload)[:200]


def _is_retryable_status(status_code: int) -> bool:
    return status_code == 429 or status_code >= 500


def _clean_string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _optional_clean_string(value: Any) -> str | None:
    cleaned = _clean_string(value)
    return cleaned or None


def _parse_published_date(value: Any) -> datetime | None:
    parsed = _clean_string(value)
    if not parsed:
        return None

    try:
        return time_str_to_utc(parsed)
    except Exception:
        return None
