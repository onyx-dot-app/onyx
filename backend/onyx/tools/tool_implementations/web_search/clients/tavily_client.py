"""Tavily web search client (https://docs.tavily.com).

MVP scope: /search endpoint only. /extract (url reader) and /qna deliberately
omitted — they overlap with existing Onyx content providers / answer flow.
"""
import json
from collections.abc import Sequence

import requests
from fastapi import HTTPException

from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.tools.tool_implementations.web_search.models import WebSearchProvider
from onyx.tools.tool_implementations.web_search.models import WebSearchResult
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_REQUEST_TIMEOUT_SECONDS = 60


class TavilyClient(WebSearchProvider):
    """Web search via Tavily Search API.

    Tavily supports the ``site:`` operator inside the query string, so we
    inherit the default ``supports_site_filter = True``.
    """

    def __init__(self, api_key: str, num_results: int = 10) -> None:
        self._api_key = api_key
        self._num_results = num_results
        self._headers = {"Content-Type": "application/json"}

    @retry_builder(tries=3, delay=1, backoff=2)
    def search(self, query: str) -> list[WebSearchResult]:
        payload = {
            "api_key": self._api_key,
            "query": query,
            "max_results": self._num_results,
            "search_depth": "basic",
            "include_raw_content": False,
            "include_answer": False,
        }

        response = requests.post(
            TAVILY_SEARCH_URL,
            headers=self._headers,
            data=json.dumps(payload),
            timeout=TAVILY_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

        raw_results = (response.json() or {}).get("results") or []

        validated: list[WebSearchResult] = []
        for item in raw_results:
            link = (item.get("url") or "").strip()
            if not link:
                continue

            published_raw = item.get("published_date")
            published_date = None
            if published_raw:
                try:
                    published_date = time_str_to_utc(published_raw)
                except Exception:
                    published_date = None

            validated.append(
                WebSearchResult(
                    title=(item.get("title") or "").strip(),
                    link=link,
                    snippet=(item.get("content") or "").strip(),
                    author=None,
                    published_date=published_date,
                )
            )

        return validated

    def test_connection(self) -> dict[str, str]:
        try:
            results = self.search("test")
            if not results or not any(r.link for r in results):
                raise HTTPException(
                    status_code=400,
                    detail="API key validation failed: search returned no results.",
                )
        except HTTPException:
            raise
        except Exception as e:
            error_msg = str(e)
            if any(s in error_msg.lower() for s in ("api", "key", "auth", "401", "403")):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid Tavily API key: {error_msg}",
                ) from e
            raise HTTPException(
                status_code=400,
                detail=f"Tavily API key validation failed: {error_msg}",
            ) from e

        logger.info("Web search provider test succeeded for Tavily.")
        return {"status": "ok"}


# Re-export type for symmetry with sibling clients (some imports use Sequence).
__all__ = ["TavilyClient", "Sequence"]
