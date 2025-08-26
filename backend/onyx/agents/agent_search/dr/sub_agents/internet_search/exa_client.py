import requests

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
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()


# TODO Dependency inject for testing
class ExaClient(InternetSearchProvider):
    def __init__(self):
        self.api_key = EXA_API_KEY
        self.api_base = "https://api.exa.ai"
        self.headers = {
            "x-api-key": EXA_API_KEY,
            "Content-Type": "application/json",
        }

    @retry_builder(tries=3, delay=1, backoff=2)
    def search(self, query: str) -> list[InternetSearchResult]:
        response = requests.post(
            self.api_base + "/search",
            headers=self.headers,
            json={
                "query": query,
                "type": "fast",
                "contents": {
                    "text": False,
                    "livecrawl": "never",
                    "highlights": {
                        "num_highlights": 1,
                        "num_sentences": 2,
                    },
                },
                "num_results": 10,
            },
            timeout=30,
        )
        response.raise_for_status()
        json_response = response.json()
        return [
            InternetSearchResult(
                title=result["title"],
                link=result["url"],
                snippet=result["highlights"][0],
                author=result.get("author"),
                published_date=result.get("published_date"),
            )
            for result in json_response["results"]
        ]

    @retry_builder(tries=3, delay=1, backoff=2)
    def contents(self, urls: list[str]) -> list[InternetContent]:
        payload = {"urls": urls, "text": True, "livecrawl": "preferred"}
        response = requests.post(
            self.api_base + "/contents",
            headers=self.headers,
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        results = response.json()["results"]
        return [
            InternetContent(
                title=result["title"],
                link=result["url"],
                full_content=result["text"],
            )
            for result in results
        ]
