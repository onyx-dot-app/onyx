from __future__ import annotations

from typing import Any

import requests
from fastapi import HTTPException

from onyx.tools.tool_implementations.web_search.models import (
    WebSearchProvider,
)
from onyx.tools.tool_implementations.web_search.models import WebSearchResult
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()

BRAVE_WEB_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
BRAVE_MAX_RESULTS_PER_REQUEST = 20
BRAVE_SAFESEARCH_OPTIONS = {"off", "moderate", "strict"}
BRAVE_FRESHNESS_OPTIONS = {"pd", "pw", "pm", "py"}


class RetryableBraveSearchError(Exception):
    """Error type used to trigger retry for transient Brave search failures."""


class BraveClient(WebSearchProvider):
    def __init__(
        self,
        api_key: str,
        *,
        num_results: int = 10,
        timeout_seconds: int = 10,
        country: str | None = None,
        search_lang: str | None = None,
        ui_lang: str | None = None,
        safesearch: str | None = None,
        freshness: str | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Brave provider config 'timeout_seconds' must be > 0.")

        self._headers = {
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
        }
        logger.debug(f"Count of results passed to BraveClient: {num_results}")
        self._num_results = max(1, min(num_results, BRAVE_MAX_RESULTS_PER_REQUEST))
        self._timeout_seconds = timeout_seconds
        self._country = _normalize_country(country)
        self._search_lang = _normalize_language_code(
            search_lang, field_name="search_lang"
        )
        self._ui_lang = _normalize_language_code(ui_lang, field_name="ui_lang")
        self._safesearch = _normalize_option(
            safesearch,
            field_name="safesearch",
            allowed_values=BRAVE_SAFESEARCH_OPTIONS,
        )
        self._freshness = _normalize_option(
            freshness,
            field_name="freshness",
            allowed_values=BRAVE_FRESHNESS_OPTIONS,
        )

    def _build_search_params(self, query: str) -> dict[str, str]:
        params = {
            "q": query,
            "count": str(self._num_results),
        }
        if self._country:
            params["country"] = self._country
        if self._search_lang:
            params["search_lang"] = self._search_lang
        if self._ui_lang:
            params["ui_lang"] = self._ui_lang
        if self._safesearch:
            params["safesearch"] = self._safesearch
        if self._freshness:
            params["freshness"] = self._freshness
        return params

    @retry_builder(
        tries=3,
        delay=1,
        backoff=2,
        exceptions=(RetryableBraveSearchError,),
    )
    def _search_with_retries(self, query: str) -> list[WebSearchResult]:
        params = self._build_search_params(query)

        try:
            response = requests.get(
                BRAVE_WEB_SEARCH_URL,
                headers=self._headers,
                params=params,
                timeout=self._timeout_seconds,
            )
        except requests.RequestException as exc:
            raise RetryableBraveSearchError(
                f"Brave search request failed: {exc}"
            ) from exc

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            error_msg = _build_error_message(response)
            if _is_retryable_status(response.status_code):
                raise RetryableBraveSearchError(error_msg) from exc
            raise ValueError(error_msg) from exc

        data = response.json()
        web_results = (data.get("web") or {}).get("results") or []

        results: list[WebSearchResult] = []
        for result in web_results:
            if not isinstance(result, dict):
                continue

            link = _clean_string(result.get("url"))
            if not link:
                continue

            title = _clean_string(result.get("title"))
            description = _clean_string(result.get("description"))

            results.append(
                WebSearchResult(
                    title=title,
                    link=link,
                    snippet=description,
                    author=None,
                    published_date=None,
                )
            )

        return results

    def search(self, query: str) -> list[WebSearchResult]:
        try:
            return self._search_with_retries(query)
        except RetryableBraveSearchError as exc:
            raise ValueError(str(exc)) from exc

    def test_connection(self) -> dict[str, str]:
        try:
            test_results = self.search("test")
            if not test_results or not any(result.link for result in test_results):
                raise HTTPException(
                    status_code=400,
                    detail="Brave API key validation failed: search returned no results.",
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
                    detail=f"Invalid Brave API key: {error_msg}",
                ) from e
            if "status 429" in lower or "rate limit" in lower:
                raise HTTPException(
                    status_code=400,
                    detail=f"Brave API rate limit exceeded: {error_msg}",
                ) from e
            raise HTTPException(
                status_code=400,
                detail=f"Brave API key validation failed: {error_msg}",
            ) from e

        logger.info("Web search provider test succeeded for Brave.")
        return {"status": "ok"}


def _build_error_message(response: requests.Response) -> str:
    return (
        "Brave search failed "
        f"(status {response.status_code}): {_extract_error_detail(response)}"
    )


def _extract_error_detail(response: requests.Response) -> str:
    try:
        payload: Any = response.json()
    except Exception:
        text = response.text.strip()
        return text[:200] if text else "No error details"

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            detail = error.get("detail") or error.get("message")
            if isinstance(detail, str):
                return detail
        if isinstance(error, str):
            return error

        message = payload.get("message")
        if isinstance(message, str):
            return message

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
            "Brave provider config 'country' must be a 2-letter ISO country code."
        )
    return normalized


def _normalize_language_code(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > 20:
        raise ValueError(f"Brave provider config '{field_name}' is too long.")
    return normalized


def _normalize_option(
    value: str | None,
    *,
    field_name: str,
    allowed_values: set[str],
) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    if normalized not in allowed_values:
        allowed = ", ".join(sorted(allowed_values))
        raise ValueError(
            f"Brave provider config '{field_name}' must be one of: {allowed}."
        )
    return normalized
