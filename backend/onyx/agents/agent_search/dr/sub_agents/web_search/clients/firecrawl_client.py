from firecrawl import Firecrawl

from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
    InternetContent,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
    InternetContentInterface,
)
from onyx.configs.chat_configs import FIRECRAWL_API_KEY
from onyx.utils.retry_wrapper import retry_builder


class FirecrawlContentClient(InternetContentInterface):
    def __init__(self, api_key: str = FIRECRAWL_API_KEY):
        self.firecrawl = Firecrawl(api_key=api_key)

    @retry_builder(tries=3, delay=1, backoff=2)
    def contents(self, urls: list[str]) -> list[InternetContent]:
        if not urls:
            return []

        results = self.firecrawl.batch_scrape(urls)

        output = [
            InternetContent(
                title=result.metadata and result.metadata.title or "",
                link=result.metadata and result.metadata.url or "",
                full_content=result.markdown or "",
                published_date=None,
            )
            for result in results.data
        ]

        failed_urls = set(urls) - set(map(lambda x: x.link, output))

        output.extend(
            [
                InternetContent(
                    title="",
                    link=url,
                    full_content="",
                    published_date=None,
                    scrape_successful=False,
                )
                for url in failed_urls
            ]
        )

        return output
