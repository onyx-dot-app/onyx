import re
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


def _extract_site_operators(query: str) -> tuple[str, list[str]]:
    """Extract site: operators and return cleaned query + full domains.

    Returns (cleaned_query, full_domains) where full_domains contains the full
    values after site: (e.g., ["reddit.com/r/leagueoflegends"]).
    """
    full_domains = re.findall(r"site:\s*([^\s]+)", query, re.IGNORECASE)
    cleaned_query = re.sub(r"site:\s*\S+\s*", "", query, flags=re.IGNORECASE).strip()

    if not cleaned_query and full_domains:
        cleaned_query = full_domains[0]

    return cleaned_query, full_domains


class ExaClient(WebSearchProvider, WebContentProvider):
    def __init__(self, api_key: str, num_results: int = 10) -> None:
        self.exa = Exa(api_key=api_key)
        self._num_results = num_results

    @property
    def supports_site_filter(self) -> bool:
        return False

    def _search_exa(
        self, query: str, include_domains: list[str] | None = None
    ) -> list[WebSearchResult]:
        response = self.exa.search_and_contents(
            query,
            type="auto",
            highlights=HighlightsContentsOptions(
                num_sentences=2,
                highlights_per_url=1,
            ),
            num_results=self._num_results,
            include_domains=include_domains,
        )

        results: list[WebSearchResult] = []
        for result in response.results:
            title = (result.title or "").strip()
            snippet = (result.highlights[0] if result.highlights else "").strip()
            results.append(
                WebSearchResult(
                    title=title,
                    link=result.url,
                    snippet=snippet,
                    author=result.author,
                    published_date=(
                        time_str_to_utc(result.published_date)
                        if result.published_date
                        else None
                    ),
                )
            )

        return results

    @retry_builder(tries=3, delay=1, backoff=2)
    def search(self, query: str) -> list[WebSearchResult]:
        cleaned_query, full_domains = _extract_site_operators(query)

        if full_domains:
            # Try with include_domains using base domains (e.g., ["reddit.com"])
            base_domains = [d.split("/")[0].removeprefix("www.") for d in full_domains]
            results = self._search_exa(cleaned_query, include_domains=base_domains)
            if results:
                return results

        # Fallback: add full domains as keywords
        query_with_domains = f"{cleaned_query} {' '.join(full_domains)}".strip()
        return self._search_exa(query_with_domains)

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

        # Exa can return partial/empty content entries; skip those to avoid
        # downstream prompt + UI pollution.
        contents: list[WebContent] = []
        for result in response.results:
            title = (result.title or "").strip()
            full_content = (result.text or "").strip()
            contents.append(
                WebContent(
                    title=title,
                    link=result.url,
                    full_content=full_content,
                    published_date=(
                        time_str_to_utc(result.published_date)
                        if result.published_date
                        else None
                    ),
                    scrape_successful=bool(full_content),
                )
            )

        return contents
