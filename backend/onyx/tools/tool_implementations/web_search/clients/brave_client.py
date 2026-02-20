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


class BraveClient(WebSearchProvider):
    def __init__(
        self,
        api_key: str,
        *,
        num_results: int = 10,
        timeout_seconds: int = 10,
    ) -> None:
        self._headers = {
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
        }
        logger.debug(f"Count of results passed to BraveClient: {num_results}")
        self._num_results = max(1, min(num_results, BRAVE_MAX_RESULTS_PER_REQUEST))
        self._timeout_seconds = timeout_seconds

    @retry_builder(tries=3, delay=1, backoff=2)
    def search(self, query: str) -> list[WebSearchResult]:
        params = {
            "q": query,
            "count": str(self._num_results),
        }

        response = requests.get(
            BRAVE_WEB_SEARCH_URL,
            headers=self._headers,
            params=params,
            timeout=self._timeout_seconds,
        )

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise ValueError(_build_error_message(response)) from exc

        data = response.json()
        web_results = (data.get("web") or {}).get("results") or []

        results: list[WebSearchResult] = []
        for result in web_results:
            link = (result.get("url") or "").strip()
            if not link:
                continue

            title = (result.get("title") or "").strip()
            description = (result.get("description") or "").strip()

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
