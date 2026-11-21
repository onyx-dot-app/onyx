from __future__ import annotations

from datetime import datetime
from typing import Any

import requests

from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.tools.tool_implementations.web_search.models import (
    WebSearchProvider,
    WebSearchResult,
)
from onyx.tools.tool_implementations.web_search.utils import extract_site_operators
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()

PARALLEL_SEARCH_URL = "https://api.parallel.ai/v1/search"
PARALLEL_MAX_RESULTS = 20
PARALLEL_MODES = ("turbo", "fast", "basic", "advanced")
PARALLEL_DEFAULT_MODE = "fast"
_DEFAULT_TIMEOUT_SECONDS = 30
_MAX_ERROR_DETAIL_CHARS = 200


class RetryableParallelSearchError(Exception):
    """Error type used to trigger retry for transient Parallel search failures."""


class ParallelSearchClient(WebSearchProvider):
    """Parallel Search API (`POST /v1/search`)."""

    def __init__(
        self,
        api_key: str,
        *,
        num_results: int = 10,
        timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
        mode: str | None = None,
        location: str | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Parallel provider config 'timeout_seconds' must be > 0.")

        self._api_key = api_key
        self._num_results = max(1, min(num_results, PARALLEL_MAX_RESULTS))
        self._timeout_seconds = timeout_seconds
        self._mode = _normalize_mode(mode)
        self._location = _normalize_location(location)

    @property
    def supports_site_filter(self) -> bool:
        # Parallel asks for plain keyword queries; `site:` maps to include_domains.
        return False

    def _build_request_body(self, query: str) -> dict[str, Any]:
        site_operators = extract_site_operators(query)
        include_domains = [
            d.removeprefix("www.") for d in site_operators.include_domains
        ]
        exclude_domains = [
            d.removeprefix("www.") for d in site_operators.exclude_domains
        ]
        advanced_settings: dict[str, Any] = {"max_results": self._num_results}
        source_policy: dict[str, list[str]] = {}
        if include_domains:
            source_policy["include_domains"] = include_domains
        if exclude_domains:
            source_policy["exclude_domains"] = exclude_domains
        if source_policy:
            advanced_settings["source_policy"] = source_policy
        if self._location:
            advanced_settings["location"] = self._location

        mode = self._mode
        # Turbo mode does not support domain/path prefixes in source_policy.
        if mode == "turbo" and any("/" in d for d in include_domains + exclude_domains):
            mode = "fast"

        return {
            "search_queries": [site_operators.query or query],
            "mode": mode,
            "advanced_settings": advanced_settings,
        }

    @retry_builder(
        tries=3,
        delay=1,
        backoff=2,
        exceptions=(RetryableParallelSearchError,),
    )
    def _search_with_retries(self, query: str) -> list[WebSearchResult]:
        headers = {
            "x-api-key": self._api_key,
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                PARALLEL_SEARCH_URL,
                headers=headers,
                json=self._build_request_body(query),
                timeout=self._timeout_seconds,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise RetryableParallelSearchError(
                f"Parallel search request failed: {exc}"
            ) from exc

        if 300 <= response.status_code < 400:
            raise ValueError(
                f"Parallel search returned a redirect (status {response.status_code})."
            )

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            error_msg = _build_error_message(response)
            if _is_retryable_status(response.status_code):
                raise RetryableParallelSearchError(error_msg) from exc
            raise ValueError(error_msg) from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise RetryableParallelSearchError(
                "Parallel search returned a non-JSON response."
            ) from exc

        _log_warnings(data)
        return _parse_results(data)

    def search(self, query: str) -> list[WebSearchResult]:
        try:
            return self._search_with_retries(query)
        except RetryableParallelSearchError as exc:
            raise ValueError(str(exc)) from exc

    def test_connection(self) -> dict[str, str]:
        try:
            test_results = self.search("test")
            if not test_results or not any(result.link for result in test_results):
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    "Parallel API key validation failed: search returned no results.",
                )
        except OnyxError:
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
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    f"Invalid Parallel API key: {error_msg}",
                ) from e
            if "status 402" in lower or "payment" in lower or "credits" in lower:
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    f"Parallel account has insufficient credits: {error_msg}",
                ) from e
            if "status 429" in lower or "rate limit" in lower:
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    f"Parallel API rate limit exceeded: {error_msg}",
                ) from e
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"Parallel API key validation failed: {error_msg}",
            ) from e

        logger.info("Web search provider test succeeded for Parallel.")
        return {"status": "ok"}


def _parse_results(data: Any) -> list[WebSearchResult]:
    raw_results = data.get("results") if isinstance(data, dict) else None
    if raw_results is None:
        raw_results = []
    if not isinstance(raw_results, list):
        raise ValueError(
            "Parallel search returned an unexpected response shape: "
            f"'results' is {type(raw_results).__name__}, expected a list."
        )

    results: list[WebSearchResult] = []
    for result in raw_results:
        if not isinstance(result, dict):
            continue

        link = _clean_string(result.get("url"))
        if not link:
            continue

        raw_excerpts = result.get("excerpts")
        excerpts = (
            [_clean_string(e) for e in raw_excerpts]
            if isinstance(raw_excerpts, list)
            else []
        )

        results.append(
            WebSearchResult(
                title=_clean_string(result.get("title")),
                link=link,
                snippet="\n\n".join(e for e in excerpts if e),
                author=None,
                published_date=_parse_publish_date(result.get("publish_date")),
            )
        )

    return results


def _parse_publish_date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return time_str_to_utc(value.strip())
    except (ValueError, OverflowError):
        return None


def _log_warnings(data: Any) -> None:
    warnings = data.get("warnings") if isinstance(data, dict) else None
    if isinstance(warnings, list) and warnings:
        logger.warning("Parallel search returned warnings: %s", warnings)


def _build_error_message(response: requests.Response) -> str:
    return (
        "Parallel search failed "
        f"(status {response.status_code}): {_extract_error_detail(response)}"
    )


def _extract_error_detail(response: requests.Response) -> str:
    try:
        payload: Any = response.json()
    except Exception:
        text = response.text.strip()
        return text[:_MAX_ERROR_DETAIL_CHARS] if text else "No error details"

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            error = error.get("message")
        detail = error or payload.get("message") or payload.get("detail")
        if isinstance(detail, str):
            return detail[:_MAX_ERROR_DETAIL_CHARS]

    return str(payload)[:_MAX_ERROR_DETAIL_CHARS]


def _is_retryable_status(status_code: int) -> bool:
    return status_code == 429 or status_code >= 500


def _clean_string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _normalize_mode(mode: str | None) -> str:
    if mode is None or not mode.strip():
        return PARALLEL_DEFAULT_MODE
    normalized = mode.strip().lower()
    if normalized not in PARALLEL_MODES:
        raise ValueError(
            f"Parallel provider config 'mode' must be one of {', '.join(PARALLEL_MODES)}."
        )
    return normalized


def _normalize_location(location: str | None) -> str | None:
    if location is None:
        return None
    normalized = location.strip().lower()
    if not normalized:
        return None
    if len(normalized) != 2 or not (normalized.isascii() and normalized.isalpha()):
        raise ValueError(
            "Parallel provider config 'location' must be a 2-letter ISO country code."
        )
    return normalized
