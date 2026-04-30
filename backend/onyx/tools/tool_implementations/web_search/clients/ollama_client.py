from __future__ import annotations

from typing import Any

import requests
from fastapi import HTTPException

from onyx.tools.tool_implementations.web_search.models import WebSearchProvider
from onyx.tools.tool_implementations.web_search.models import WebSearchResult
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()

OLLAMA_WEB_SEARCH_URL = "https://ollama.com/api/web_search"
OLLAMA_MAX_RESULTS = 10


class RetryableOllamaSearchError(Exception):
    """Error type used to trigger retry for transient Ollama search failures."""


class OllamaClient(WebSearchProvider):
    def __init__(
        self,
        api_key: str,
        *,
        num_results: int = 10,
        timeout_seconds: int = 15,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Ollama provider config 'timeout_seconds' must be > 0.")

        self._headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        self._num_results = max(1, min(num_results, OLLAMA_MAX_RESULTS))
        self._timeout_seconds = timeout_seconds

    @retry_builder(
        tries=3,
        delay=1,
        backoff=2,
        exceptions=(RetryableOllamaSearchError,),
    )
    def _search_with_retries(self, query: str) -> list[WebSearchResult]:
        payload: dict[str, Any] = {
            "query": query,
            "max_results": self._num_results,
        }

        try:
            response = requests.post(
                OLLAMA_WEB_SEARCH_URL,
                headers=self._headers,
                json=payload,
                timeout=self._timeout_seconds,
            )
        except requests.RequestException as exc:
            raise RetryableOllamaSearchError(
                f"Ollama search request failed: {exc}"
            ) from exc

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            status_code = response.status_code
            error_msg = f"Ollama search API error (status {status_code}): {response.text}"
            if _is_retryable_status(status_code):
                raise RetryableOllamaSearchError(error_msg) from exc
            raise ValueError(error_msg) from exc

        data = response.json()
        results_list = data.get("results") or []

        search_results: list[WebSearchResult] = []
        for result in results_list:
            if not isinstance(result, dict):
                continue

            link = (result.get("url") or "").strip()
            if not link:
                continue

            title = (result.get("title") or "").strip()
            content = (result.get("content") or "").strip()

            search_results.append(
                WebSearchResult(
                    title=title,
                    link=link,
                    snippet=content,
                )
            )

        return search_results

    def search(self, query: str) -> list[WebSearchResult]:
        try:
            return self._search_with_retries(query)
        except RetryableOllamaSearchError as exc:
            raise ValueError(str(exc)) from exc

    def test_connection(self) -> dict[str, str]:
        try:
            test_results = self.search("test")
            if not test_results or not any(result.link for result in test_results):
                raise HTTPException(
                    status_code=400,
                    detail="Ollama API key validation failed: search returned no results.",
                )
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=str(exc),
            ) from exc

        logger.info("Web search provider test succeeded for Ollama.")
        return {"status": "ok"}


def _is_retryable_status(status_code: int) -> bool:
    return status_code in (408, 429, 500, 502, 503, 504)