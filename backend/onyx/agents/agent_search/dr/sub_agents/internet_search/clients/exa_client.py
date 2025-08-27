from exa_py import Exa
from exa_py.api import HighlightsContentsOptions

from onyx.agents.agent_search.dr.sub_agents.internet_search.models import (
    InternetContent,
)
from onyx.agents.agent_search.dr.sub_agents.internet_search.models import (
    InternetSearchProvider,
)
from onyx.agents.agent_search.dr.sub_agents.internet_search.models import (
    InternetSearchResult,
)
from onyx.configs.chat_configs import EXA_API_KEY
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.utils.retry_wrapper import retry_builder


# TODO Dependency inject for testing
class ExaClient(InternetSearchProvider):
    def __init__(self, api_key: str | None = EXA_API_KEY) -> None:
        self.exa = Exa(api_key=api_key)

    @retry_builder(tries=3, delay=1, backoff=2)
    def search(self, query: str) -> list[InternetSearchResult]:
        response = self.exa.search_and_contents(
            query=query,
            type="fast",
            text=False,
            livecrawl="never",
            highlights=HighlightsContentsOptions(
                num_sentences=2,
                num_highlights=1,
            ),
            num_results=10,
        )

        return [
            InternetSearchResult(
                title=result.title,
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
    def contents(self, urls: list[str]) -> list[InternetContent]:
        response = self.exa.get_contents(
            urls=urls,
            text=True,
            livecrawl="preferred",
        )

        return [
            InternetContent(
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
