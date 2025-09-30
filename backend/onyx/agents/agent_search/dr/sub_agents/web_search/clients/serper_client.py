import json
from concurrent.futures import ThreadPoolExecutor

import requests

from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
    InternetContent,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
    InternetSearchProvider,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
    InternetSearchResult,
)
from onyx.configs.chat_configs import SERPER_API_KEY
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.utils.retry_wrapper import retry_builder

SERPER_SEARCH_URL = "https://google.serper.dev/search"
SERPER_CONTENTS_URL = "https://scrape.serper.dev"


class SerperClient(InternetSearchProvider):
    def __init__(self, api_key: str | None = SERPER_API_KEY) -> None:
        self.headers = {
            "X-API-KEY": api_key,
            "Content-Type": "application/json",
        }

    @retry_builder(tries=3, delay=1, backoff=2)
    def search(self, query: str) -> list[InternetSearchResult]:
        payload = {
            "q": query,
        }

        response = requests.post(
            SERPER_SEARCH_URL,
            headers=self.headers,
            data=json.dumps(payload),
        )

        results = response.json()
        organic_results = results["organic"]

        return [
            InternetSearchResult(
                title=result["title"],
                link=result["link"],
                snippet=result["snippet"],
                author=None,
                published_date=None,
            )
            for result in organic_results
        ]

    def contents(self, urls: list[str]) -> list[InternetContent]:
        if not urls:
            return []

        with ThreadPoolExecutor(max_workers=min(8, len(urls))) as e:
            return list(e.map(self._get_webpage_content, urls))

    @retry_builder(tries=3, delay=1, backoff=2)
    def _get_webpage_content(self, url: str) -> InternetContent:
        payload = {
            "url": url,
        }

        response = requests.post(
            SERPER_CONTENTS_URL,
            headers=self.headers,
            data=json.dumps(payload),
        )

        if response.status_code == 400:
            return InternetContent(
                title="",
                link=url,
                full_content="",
                published_date=None,
                scrape_successful=False,
            )

        response_json = response.json()

        # Response only guarantees text
        text = response_json["text"]
        
        # metadata & jsonld is not guaranteed to be present
        metadata = response_json.get("metadata", {})
        jsonld = response_json.get("jsonld", {})

        title = extract_title_from_metadata(metadata)

        # Serper does not provide a reliable mechanism to extract the url
        response_url = url
        published_date_str = extract_published_date_from_jsonld(jsonld)
        published_date = None

        if published_date_str:
            try:
                published_date = time_str_to_utc(published_date_str)
            except Exception:
                published_date = None

        return InternetContent(
            title=title or "",
            link=response_url,
            full_content=text or "",
            published_date=published_date,
        )


def extract_title_from_metadata(metadata: dict[str, str]) -> str | None:
    keys = ["title", "og:title"]
    return extract_value_from_dict(metadata, keys)


def extract_published_date_from_jsonld(jsonld: dict[str, str]) -> str | None:
    keys = ["dateModified"]
    return extract_value_from_dict(jsonld, keys)


def extract_value_from_dict(data: dict[str, str], keys: list[str]) -> str | None:
    for key in keys:
        if key in data:
            return data[key]
    return None
