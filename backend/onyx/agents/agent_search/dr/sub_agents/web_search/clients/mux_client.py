from onyx.agents.agent_search.dr.sub_agents.web_search.models import InternetContent
from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
    InternetContentInterface,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
    InternetSearchInterface,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
    InternetSearchProvider,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
    InternetSearchResult,
)


class MuxClient(InternetSearchProvider):
    def __init__(
        self,
        search_client: InternetSearchInterface,
        content_client: InternetContentInterface,
    ):
        self.search_client = search_client
        self.content_client = content_client

    def search(self, query: str) -> list[InternetSearchResult]:
        return self.search_client.search(query)

    def contents(self, urls: list[str]) -> list[InternetContent]:
        return self.content_client.contents(urls)
