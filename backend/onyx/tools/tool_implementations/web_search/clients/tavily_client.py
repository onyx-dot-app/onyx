from __future__ import annotations

from typing import Any

import requests
from fastapi import HTTPException

from onyx.tools.tool_implementations.web_search.models import WebSearchProvider
from onyx.tools.tool_implementations.web_search.models import WebSearchResult
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_MAX_RESULTS = 20
TAVILY_SEARCH_DEPTH_OPTIONS = {"basic", "advanced"}
TAVILY_TOPIC_OPTIONS = {"general", "news"}


class RetryableTavilySearchError(Exception):
    """Error type used to trigger retry for transient Tavily search failures."""


class TavilyClient(WebSearchProvider):
    def __init__(
        self,
        api_key: str,
        *,
        num_results: int = 10,
        search_depth: str | None = None,
        topic: str | None = None,
        country: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._num_results = max(1, min(num_results, TAVILY_MAX_RESULTS))
        self._search_depth = _normalize_option(
            search_depth,
            field_name="search_depth",
            allowed_values=TAVILY_SEARCH_DEPTH_OPTIONS,
            default="basic",
        )
        self._topic = _normalize_option(
            topic,
            field_name="topic",
            allowed_values=TAVILY_TOPIC_OPTIONS,
            default="general",
        )
        self._country = _normalize_country(country)

    def _build_request_body(self, query: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "query": query,
            "max_results": self._num_results,
            "search_depth": self._search_depth,
            "topic": self._topic,
        }
        if self._country:
            body["country"] = self._country
        return body

    @retry_builder(
        tries=3,
        delay=1,
        backoff=2,
        exceptions=(RetryableTavilySearchError,),
    )
    def _search_with_retries(self, query: str) -> list[WebSearchResult]:
        body = self._build_request_body(query)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                TAVILY_SEARCH_URL,
                headers=headers,
                json=body,
                timeout=30,
            )
        except requests.RequestException as exc:
            raise RetryableTavilySearchError(
                f"Tavily search request failed: {exc}"
            ) from exc

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            error_msg = _build_error_message(response)
            if _is_retryable_status(response.status_code):
                raise RetryableTavilySearchError(error_msg) from exc
            raise ValueError(error_msg) from exc

        data = response.json()
        raw_results = data.get("results") or []

        results: list[WebSearchResult] = []
        for result in raw_results:
            if not isinstance(result, dict):
                continue

            link = _clean_string(result.get("url"))
            if not link:
                continue

            title = _clean_string(result.get("title"))
            snippet = _clean_string(result.get("content"))

            results.append(
                WebSearchResult(
                    title=title,
                    link=link,
                    snippet=snippet,
                    author=None,
                    published_date=None,
                )
            )

        return results

    def search(self, query: str) -> list[WebSearchResult]:
        try:
            return self._search_with_retries(query)
        except RetryableTavilySearchError as exc:
            raise ValueError(str(exc)) from exc

    def test_connection(self) -> dict[str, str]:
        try:
            test_results = self.search("test")
            if not test_results or not any(result.link for result in test_results):
                raise HTTPException(
                    status_code=400,
                    detail="Tavily API key validation failed: search returned no results.",
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
                    detail=f"Invalid Tavily API key: {error_msg}",
                ) from e
            if "status 429" in lower or "rate limit" in lower:
                raise HTTPException(
                    status_code=400,
                    detail=f"Tavily API rate limit exceeded: {error_msg}",
                ) from e
            raise HTTPException(
                status_code=400,
                detail=f"Tavily API key validation failed: {error_msg}",
            ) from e

        logger.info("Web search provider test succeeded for Tavily.")
        return {"status": "ok"}


def _build_error_message(response: requests.Response) -> str:
    return (
        "Tavily search failed "
        f"(status {response.status_code}): {_extract_error_detail(response)}"
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


def _is_retryable_status(status_code: int) -> bool:
    return status_code == 429 or status_code >= 500


def _clean_string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _normalize_country(country: str | None) -> str | None:
    if country is None:
        return None
    normalized = country.strip().upper()
    if not normalized:
        return None
    if len(normalized) != 2 or not normalized.isalpha():
        raise ValueError(
            "Tavily provider config 'country' must be a 2-letter ISO country code."
        )
    return normalized


def _normalize_option(
    value: str | None,
    *,
    field_name: str,
    allowed_values: set[str],
    default: str,
) -> str:
    if value is None:
        return default
    normalized = value.strip().lower()
    if not normalized:
        return default
    if normalized not in allowed_values:
        allowed = ", ".join(sorted(allowed_values))
        raise ValueError(
            f"Tavily provider config '{field_name}' must be one of: {allowed}."
        )
    return normalized
