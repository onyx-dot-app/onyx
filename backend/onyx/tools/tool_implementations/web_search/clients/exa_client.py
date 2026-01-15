from collections.abc import Sequence

from exa_py import Exa
from exa_py.api import HighlightsContentsOptions
from fastapi import HTTPException

from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.tools.tool_implementations.open_url.models import WebContent
from onyx.tools.tool_implementations.open_url.models import WebContentProvider
from onyx.tools.tool_implementations.web_search.models import (
    WebSearchProvider,
)
from onyx.tools.tool_implementations.web_search.models import (
    WebSearchResult,
)
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()


# TODO can probably break this up
class ExaClient(WebSearchProvider, WebContentProvider):
    def __init__(self, api_key: str, num_results: int = 10) -> None:
        self.exa = Exa(api_key=api_key)
        self._num_results = num_results

    @retry_builder(tries=3, delay=1, backoff=2)
    def search(self, query: str) -> list[WebSearchResult]:
        response = self.exa.search_and_contents(
            query,
            type="auto",
            highlights=HighlightsContentsOptions(
                num_sentences=2,
                highlights_per_url=1,
            ),
            num_results=self._num_results,
        )

        return [
            WebSearchResult(
                title=result.title or "",
                link=result.url,
                snippet=result.highlights[0] if result.highlights else "",
                author=result.author,
                published_date=(
                    time_str_to_utc(result.published_date)
                    if result.published_date
                    else None
                ),
            )
            for result in response.results
        ]

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
            if (
                "api" in error_msg.lower()
                or "key" in error_msg.lower()
                or "auth" in error_msg.lower()
            ):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid Exa API key: {error_msg}",
                ) from e
            raise HTTPException(
                status_code=400,
                detail=f"Exa API key validation failed: {error_msg}",
            ) from e

        logger.info("Web search provider test succeeded for Exa.")
        return {"status": "ok"}

    @retry_builder(tries=3, delay=1, backoff=2)
    def contents(self, urls: Sequence[str]) -> list[WebContent]:
        response = self.exa.get_contents(
            urls=list(urls),
            text=True,
            livecrawl="preferred",
        )

        return [
            WebContent(
                title=result.title or "",
                link=result.url,
                full_content=result.text or "",
                published_date=(
                    time_str_to_utc(result.published_date)
                    if result.published_date
                    else None
                ),
            )
            for result in response.results
        ]
