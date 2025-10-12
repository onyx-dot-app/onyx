from exa_py import Exa
from exa_py.api import HighlightsContentsOptions

from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
    WebContent,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
    WebSearchProvider,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
    WebSearchResult,
)
from onyx.configs.chat_configs import EXA_API_KEY
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.utils.retry_wrapper import retry_builder


class ExaClient(WebSearchProvider):
    def __init__(self, api_key: str | None = EXA_API_KEY) -> None:
        self.exa = Exa(api_key=api_key)

    @retry_builder(tries=3, delay=1, backoff=2)
    def search(self, query: str) -> list[WebSearchResult]:
        response = self.exa.search_and_contents(
            query,
            type="auto",
            highlights=HighlightsContentsOptions(
                num_sentences=2,
                highlights_per_url=1,
            ),
            num_results=10,
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

    @retry_builder(tries=3, delay=1, backoff=2)
    def contents(self, urls: list[str]) -> list[WebContent]:
        response = self.exa.get_contents(
            urls=urls,
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
