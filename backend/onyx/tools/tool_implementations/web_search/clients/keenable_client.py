import json
from typing import Any
from urllib.parse import urlsplit

import requests
from fastapi import HTTPException

from onyx.tools.tool_implementations.web_search.models import WebSearchProvider
from onyx.tools.tool_implementations.web_search.models import WebSearchResult
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()

KEENABLE_DEFAULT_BASE_URL = "https://api.keenable.ai"
KEENABLE_REQUEST_TIMEOUT_SECONDS = 30


class RetryableKeenableSearchError(Exception):
    """Error type used to trigger retry for transient Keenable search failures."""


class KeenableClient(WebSearchProvider):
    """Keenable web search provider.

    Keenable is a web search API built for AI agents. Unlike most providers it
    works without an API key by default: with no key the keyless public endpoint
    is used. Passing an API key uses the authenticated endpoint and lifts rate
    limits.
    """

    def __init__(
        self,
        api_key: str | None = None,
        num_results: int = 10,
        base_url: str | None = None,
    ) -> None:
        self._api_key = (api_key or "").strip() or None
        self._num_results = num_results
        self._base_url = self._normalize_base_url(base_url)

    @staticmethod
    def _normalize_base_url(base_url: str | None) -> str:
        base = (base_url or KEENABLE_DEFAULT_BASE_URL).rstrip("/")
        parsed = urlsplit(base)
        if parsed.hostname:
            if parsed.scheme == "https":
                return base
            # Permit plain http only against a loopback host (local dev).
            if parsed.scheme == "http" and parsed.hostname in {
                "localhost",
                "127.0.0.1",
                "::1",
            }:
                return base
        raise ValueError(
            f"Keenable base URL must be an https:// URL with a host, got {base!r}"
        )

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "keenable-onyx",
            # Attribution header the Keenable backend segments traffic by.
            "X-Keenable-Title": "Onyx",
        }
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        return headers

    @retry_builder(
        tries=3,
        delay=1,
        backoff=2,
        exceptions=(RetryableKeenableSearchError,),
    )
    def _search_with_retries(self, query: str) -> list[WebSearchResult]:
        # Keyless public endpoint by default; keyed endpoint when a key is set.
        path = "/v1/search" if self._api_key else "/v1/search/public"
        try:
            response = requests.post(
                f"{self._base_url}{path}",
                headers=self._headers(),
                data=json.dumps({"query": query, "mode": "pro"}),
                timeout=KEENABLE_REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise RetryableKeenableSearchError(
                f"Keenable search request failed: {exc}"
            ) from exc

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            error_msg = _build_error_message(response)
            if _is_retryable_status(response.status_code):
                raise RetryableKeenableSearchError(error_msg) from exc
            raise ValueError(error_msg) from exc

        body = response.json()
        results = body.get("results") if isinstance(body, dict) else None
        if not isinstance(results, list):
            return []

        validated_results: list[WebSearchResult] = []
        for result in results[: self._num_results]:
            if not isinstance(result, dict):
                continue
            link = (result.get("url") or "").strip()
            if not link:
                continue
            validated_results.append(
                WebSearchResult(
                    title=(result.get("title") or "").strip(),
                    link=link,
                    snippet=(result.get("description") or "").strip(),
                    author=result.get("author"),
                    published_date=None,
                )
            )

        return validated_results

    def search(self, query: str) -> list[WebSearchResult]:
        try:
            return self._search_with_retries(query)
        except RetryableKeenableSearchError as exc:
            raise ValueError(str(exc)) from exc

    def test_connection(self) -> dict[str, str]:
        try:
            test_results = self.search("test")
            if not test_results or not any(result.link for result in test_results):
                raise HTTPException(
                    status_code=400,
                    detail="Keenable validation failed: search returned no results.",
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
                    detail=f"Invalid Keenable API key: {error_msg}",
                ) from e
            if "status 429" in lower or "rate limit" in lower:
                raise HTTPException(
                    status_code=400,
                    detail=f"Keenable rate limit exceeded: {error_msg}",
                ) from e
            raise HTTPException(
                status_code=400,
                detail=f"Keenable validation failed: {error_msg}",
            ) from e

        logger.info("Web search provider test succeeded for Keenable.")
        return {"status": "ok"}


def _build_error_message(response: requests.Response) -> str:
    return (
        f"Keenable search failed (status {response.status_code}): "
        f"{_extract_error_detail(response)}"
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

        message = payload.get("message") or payload.get("detail")
        if isinstance(message, str):
            return message

    return str(payload)[:200]


def _is_retryable_status(status_code: int) -> bool:
    return status_code == 429 or status_code >= 500
