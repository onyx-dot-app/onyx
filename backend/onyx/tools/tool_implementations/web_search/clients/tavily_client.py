from collections.abc import Sequence

from fastapi import HTTPException
from tavily import TavilyClient as _TavilyClient

from onyx.tools.tool_implementations.web_search.models import (
    WebSearchProvider,
)
from onyx.tools.tool_implementations.web_search.models import WebSearchResult
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()


class TavilyClient(WebSearchProvider):
    def __init__(self, api_key: str, num_results: int = 10) -> None:
        self._client = _TavilyClient(api_key=api_key)
        self._num_results = num_results

    @retry_builder(tries=3, delay=1, backoff=2)
    def search(self, query: str) -> Sequence[WebSearchResult]:
        response = self._client.search(
            query=query,
            max_results=self._num_results,
            search_depth="basic",
        )

        results: list[WebSearchResult] = []
        for item in response.get("results", []):
            url = (item.get("url") or "").strip()
            if not url:
                continue

            title = (item.get("title") or "").strip()
            snippet = (item.get("content") or "").strip()

            results.append(
                WebSearchResult(
                    title=title,
                    link=url,
                    snippet=snippet,
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
                    detail="API key validation failed: search returned no results.",
                )
        except HTTPException:
            raise
        except Exception as e:
            error_msg = str(e)
            lower = error_msg.lower()
            if "api" in lower or "key" in lower or "auth" in lower:
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
