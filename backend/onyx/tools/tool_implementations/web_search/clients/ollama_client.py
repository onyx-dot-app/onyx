from __future__ import annotations

import requests

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.tools.tool_implementations.web_search.models import (
    WebSearchProvider,
    WebSearchResult,
)
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()

OLLAMA_WEB_SEARCH_URL = "https://ollama.com/api/web_search"
OLLAMA_MAX_RESULTS = 10


class RetryableOllamaSearchError(Exception):
    """Error type used to trigger retry for transient Ollama search failures."""


class OllamaClient(WebSearchProvider):
    """Web search provider backed by Ollama's hosted web search API."""

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
        """Run one search request, raising RetryableOllamaSearchError on transient failures."""
        payload: dict[str, str | int] = {
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
            error_msg = (
                f"Ollama search API error (status {status_code}): {response.text}"
            )
            if _is_retryable_status(status_code):
                raise RetryableOllamaSearchError(error_msg) from exc
            raise ValueError(error_msg) from exc

        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Ollama search API returned an unexpected response shape.")

        results_list = data.get("results")
        if results_list is None:
            results_list = []
        if not isinstance(results_list, list):
            raise ValueError("Ollama search API returned a non-list 'results' field.")

        search_results: list[WebSearchResult] = []
        for result in results_list:
            if not isinstance(result, dict):
                continue

            link = _get_str_field(result, "url")
            if not link:
                continue

            title = _get_str_field(result, "title")
            content = _get_str_field(result, "content")

            search_results.append(
                WebSearchResult(
                    title=title,
                    link=link,
                    snippet=content,
                )
            )

        return search_results

    def search(self, query: str) -> list[WebSearchResult]:
        """Search the web, raising ValueError once retries are exhausted."""
        try:
            return self._search_with_retries(query)
        except RetryableOllamaSearchError as exc:
            raise ValueError(str(exc)) from exc

    def test_connection(self) -> dict[str, str]:
        """Validate the API key with a test search; an empty result set still counts as success."""
        try:
            self.search("test")
        except ValueError as exc:
            raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(exc)) from exc

        logger.info("Web search provider test succeeded for Ollama.")
        return {"status": "ok"}


def _get_str_field(result: dict[str, object], key: str) -> str:
    """Return a stripped string field, raising ValueError if it is present but not a string."""
    value = result.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"Ollama search API returned a non-string '{key}' field.")
    return value.strip()


def _is_retryable_status(status_code: int) -> bool:
    """Retry on request timeout, rate limiting, and any 5xx server error."""
    return status_code in (408, 429) or 500 <= status_code < 600
