from __future__ import annotations

from typing import Any

import requests
from fastapi import HTTPException

from onyx.tools.tool_implementations.web_search.models import (
    WebSearchProvider,
    WebSearchResult,
)
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()

FIRECRAWL_SEARCH_URL = "https://api.firecrawl.dev/v2/search"
FIRECRAWL_MAX_RESULTS = 100
FIRECRAWL_TBS_PRESETS = {"qdr:h", "qdr:d", "qdr:w", "qdr:m", "qdr:y"}
FIRECRAWL_TBS_CUSTOM_PREFIX = "cdr:"
_DEFAULT_TIMEOUT_SECONDS = 30
_MAX_ERROR_DETAIL_CHARS = 200


class RetryableFirecrawlSearchError(Exception):
    """Error type used to trigger retry for transient Firecrawl search failures."""


class FirecrawlSearchClient(WebSearchProvider):
    """Web search through the Firecrawl `/v2/search` endpoint.

    This is the search half of the Firecrawl integration. Page fetching is
    handled separately by `open_url.firecrawl.FirecrawlClient`. Both use the
    same Firecrawl API key.

    Firecrawl forwards the `site:` operator to the search engine, so the
    inherited `supports_site_filter = True` default applies.
    """

    def __init__(
        self,
        api_key: str,
        *,
        num_results: int = 10,
        base_url: str | None = None,
        timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
        tbs: str | None = None,
        location: str | None = None,
        country: str | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Firecrawl provider config 'timeout_seconds' must be > 0.")

        self._api_key = api_key
        self._num_results = max(1, min(num_results, FIRECRAWL_MAX_RESULTS))
        self._base_url = _normalize_base_url(base_url)
        self._timeout_seconds = timeout_seconds
        self._tbs = _normalize_tbs(tbs)
        self._location = _normalize_location(location)
        self._country = _normalize_country(country)

    def _build_request_body(self, query: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "query": query,
            "limit": self._num_results,
            "sources": ["web"],
        }
        if self._tbs:
            body["tbs"] = self._tbs
        if self._location:
            body["location"] = self._location
        if self._country:
            body["country"] = self._country
        return body

    @retry_builder(
        tries=3,
        delay=1,
        backoff=2,
        exceptions=(RetryableFirecrawlSearchError,),
    )
    def _search_with_retries(self, query: str) -> list[WebSearchResult]:
        body = self._build_request_body(query)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                self._base_url,
                headers=headers,
                json=body,
                timeout=self._timeout_seconds,
            )
        except requests.RequestException as exc:
            raise RetryableFirecrawlSearchError(
                f"Firecrawl search request failed: {exc}"
            ) from exc

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            error_msg = _build_error_message(response)
            if _is_retryable_status(response.status_code):
                raise RetryableFirecrawlSearchError(error_msg) from exc
            raise ValueError(error_msg) from exc

        try:
            data = response.json()
        except ValueError as exc:
            # A 200 with a non-JSON body is a transient gateway or proxy fault.
            raise RetryableFirecrawlSearchError(
                "Firecrawl search returned a non-JSON response."
            ) from exc

        if isinstance(data, dict) and data.get("success") is False:
            raise ValueError(
                "Firecrawl search failed: "
                f"{data.get('error') or 'Unknown error from Firecrawl.'}"
            )

        return _parse_results(data)

    def search(self, query: str) -> list[WebSearchResult]:
        try:
            return self._search_with_retries(query)
        except RetryableFirecrawlSearchError as exc:
            raise ValueError(str(exc)) from exc

    def test_connection(self) -> dict[str, str]:
        try:
            test_results = self.search("test")
            if not test_results or not any(result.link for result in test_results):
                raise HTTPException(
                    status_code=400,
                    detail="Firecrawl API key validation failed: search returned no results.",
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
                or "unauthorized" in lower
            ):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid Firecrawl API key: {error_msg}",
                ) from e
            if "status 402" in lower or "payment" in lower or "credits" in lower:
                raise HTTPException(
                    status_code=400,
                    detail=f"Firecrawl account has insufficient credits: {error_msg}",
                ) from e
            if "status 429" in lower or "rate limit" in lower:
                raise HTTPException(
                    status_code=400,
                    detail=f"Firecrawl API rate limit exceeded: {error_msg}",
                ) from e
            raise HTTPException(
                status_code=400,
                detail=f"Firecrawl API key validation failed: {error_msg}",
            ) from e

        logger.info("Web search provider test succeeded for Firecrawl.")
        return {"status": "ok"}


def _parse_results(data: Any) -> list[WebSearchResult]:
    # v2 returns {"success": true, "data": {"web": [...], "news": [...], ...}}.
    # Only the `web` source is requested, so only that list is read.
    data_section = data.get("data") if isinstance(data, dict) else None
    raw_results = data_section.get("web") if isinstance(data_section, dict) else None
    if raw_results is None:
        raw_results = []
    if not isinstance(raw_results, list):
        raise ValueError(
            "Firecrawl search returned an unexpected response shape: "
            f"'data.web' is {type(raw_results).__name__}, expected a list."
        )

    results: list[WebSearchResult] = []
    for result in raw_results:
        if not isinstance(result, dict):
            continue

        link = _clean_string(result.get("url"))
        if not link:
            continue

        results.append(
            WebSearchResult(
                title=_clean_string(result.get("title")),
                link=link,
                snippet=_clean_string(result.get("description")),
                # Firecrawl search results do not carry author or publish date
                # without scraping each page, so these stay unset.
                author=None,
                published_date=None,
            )
        )

    return results


def _build_error_message(response: requests.Response) -> str:
    return (
        "Firecrawl search failed "
        f"(status {response.status_code}): {_extract_error_detail(response)}"
    )


def _extract_error_detail(response: requests.Response) -> str:
    try:
        payload: Any = response.json()
    except Exception:
        text = response.text.strip()
        return text[:_MAX_ERROR_DETAIL_CHARS] if text else "No error details"

    if isinstance(payload, dict):
        detail = payload.get("error") or payload.get("message") or payload.get("detail")
        if isinstance(detail, str):
            return detail[:_MAX_ERROR_DETAIL_CHARS]

    return str(payload)[:_MAX_ERROR_DETAIL_CHARS]


def _is_retryable_status(status_code: int) -> bool:
    return status_code == 429 or status_code >= 500


def _clean_string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _normalize_base_url(base_url: str | None) -> str:
    if base_url is None:
        return FIRECRAWL_SEARCH_URL
    normalized = base_url.strip()
    if not normalized:
        return FIRECRAWL_SEARCH_URL
    if not normalized.startswith(("http://", "https://")):
        raise ValueError(
            "Firecrawl provider config 'base_url' must start with http:// or https://."
        )
    return normalized


def _normalize_tbs(tbs: str | None) -> str | None:
    if tbs is None:
        return None
    normalized = tbs.strip().lower()
    if not normalized:
        return None
    if normalized in FIRECRAWL_TBS_PRESETS or normalized.startswith(
        FIRECRAWL_TBS_CUSTOM_PREFIX
    ):
        return normalized
    allowed = ", ".join(sorted(FIRECRAWL_TBS_PRESETS))
    raise ValueError(
        f"Firecrawl provider config 'tbs' must be one of {allowed}, "
        f"or a custom range starting with '{FIRECRAWL_TBS_CUSTOM_PREFIX}'."
    )


def _normalize_location(location: str | None) -> str | None:
    if location is None:
        return None
    normalized = location.strip()
    return normalized or None


def _normalize_country(country: str | None) -> str | None:
    if country is None:
        return None
    normalized = country.strip().upper()
    if not normalized:
        return None
    if len(normalized) != 2 or not normalized.isalpha():
        raise ValueError(
            "Firecrawl provider config 'country' must be a 2-letter ISO country code."
        )
    return normalized
