from collections.abc import Sequence
from datetime import datetime

import requests

from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
    WebContent,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
    WebSearchProvider,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
    WebSearchResult,
)
from onyx.utils.retry_wrapper import retry_builder


class YouClient(WebSearchProvider):
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.base_url = "https://ydc-index.io/v1"

    @retry_builder(tries=3, delay=1, backoff=2)
    def search(self, query: str) -> list[WebSearchResult]:
        headers = {
            "X-API-Key": self.api_key,
        }
        params = {
            "query": query,
            "count": 10,
        }

        response = requests.get(
            f"{self.base_url}/search",
            headers=headers,
            params=params,
            timeout=10,
        )
        response.raise_for_status()

        data = response.json()
        results = []

        # Process web results
        for result in data.get("results", []):
            published_date = None
            if result.get("age"):
                try:
                    published_date = datetime.fromisoformat(
                        result["age"].replace("Z", "+00:00")
                    )
                except (ValueError, AttributeError):
                    pass

            results.append(
                WebSearchResult(
                    title=result.get("title", ""),
                    link=result.get("url", ""),
                    snippet=result.get("description", ""),
                    author=None,
                    published_date=published_date,
                )
            )

        return results

    @retry_builder(tries=3, delay=1, backoff=2)
    def contents(self, urls: Sequence[str]) -> list[WebContent]:
        # You.com doesn't have a separate contents endpoint
        # We'll use the livecrawl feature in the search endpoint
        results = []
        headers = {
            "X-API-Key": self.api_key,
        }

        for url in urls:
            params = {
                "query": url,
                "count": 1,
                "livecrawl": "web",
                "livecrawl_formats": "markdown",
            }

            try:
                response = requests.get(
                    f"{self.base_url}/search",
                    headers=headers,
                    params=params,
                    timeout=15,
                )
                response.raise_for_status()
                data = response.json()

                for result in data.get("results", []):
                    published_date = None
                    if result.get("age"):
                        try:
                            published_date = datetime.fromisoformat(
                                result["age"].replace("Z", "+00:00")
                            )
                        except (ValueError, AttributeError):
                            pass

                    results.append(
                        WebContent(
                            title=result.get("title", ""),
                            link=result.get("url", ""),
                            full_content=result.get("description", ""),
                            published_date=published_date,
                        )
                    )
            except Exception:
                # If fetching content fails for a URL, continue with others
                continue

        return results
