from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

import requests

from onyx.agents.agent_search.dr.sub_agents.web_search.models import WebContent
from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
    WebSearchProvider,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.models import WebSearchResult
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()

GOOGLE_CUSTOM_SEARCH_URL = "https://customsearch.googleapis.com/customsearch/v1"


class GooglePSEClient(WebSearchProvider):
    def __init__(
        self,
        api_key: str,
        search_engine_id: str,
        *,
        num_results: int = 10,
        timeout_seconds: int = 10,
    ) -> None:
        self._api_key = api_key
        self._search_engine_id = search_engine_id
        self._num_results = num_results
        self._timeout_seconds = timeout_seconds

    @retry_builder(tries=3, delay=1, backoff=2)
    def search(self, query: str) -> list[WebSearchResult]:
        params: dict[str, str] = {
            "key": self._api_key,
            "cx": self._search_engine_id,
            "q": query,
            "num": str(self._num_results),
        }

        response = requests.get(
            GOOGLE_CUSTOM_SEARCH_URL, params=params, timeout=self._timeout_seconds
        )
        response.raise_for_status()

        data = response.json()
        items: list[dict[str, Any]] = data.get("items", [])
        results: list[WebSearchResult] = []

        for item in items:
            link = item.get("link")
            if not link:
                continue

            snippet = item.get("snippet") or ""

            # Attempt to extract metadata if available
            pagemap = item.get("pagemap") or {}
            metatags = pagemap.get("metatags", [])
            published_date: datetime | None = None
            author: str | None = None

            if metatags:
                meta = metatags[0]
                author = meta.get("og:site_name") or meta.get("author")
                published_str = (
                    meta.get("article:published_time")
                    or meta.get("og:updated_time")
                    or meta.get("date")
                )
                if published_str:
                    try:
                        published_date = datetime.fromisoformat(
                            published_str.replace("Z", "+00:00")
                        )
                    except ValueError:
                        published_date = None

            results.append(
                WebSearchResult(
                    title=item.get("title") or "",
                    link=link,
                    snippet=snippet,
                    author=author,
                    published_date=published_date,
                )
            )

        return results

    def contents(self, urls: Sequence[str]) -> list[WebContent]:
        logger.warning(
            "Google PSE does not support content fetching; returning empty results."
        )
        return [
            WebContent(
                title="",
                link=url,
                full_content="",
                published_date=None,
                scrape_successful=False,
            )
            for url in urls
        ]
