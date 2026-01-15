import json
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor

import requests
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

SERPER_SEARCH_URL = "https://google.serper.dev/search"
SERPER_CONTENTS_URL = "https://scrape.serper.dev"


class SerperClient(WebSearchProvider, WebContentProvider):
    def __init__(self, api_key: str, num_results: int = 10) -> None:
        self.headers = {
            "X-API-KEY": api_key,
            "Content-Type": "application/json",
        }
        self._num_results = num_results

    @retry_builder(tries=3, delay=1, backoff=2)
    def search(self, query: str) -> list[WebSearchResult]:
        payload = {
            "q": query,
            "num": self._num_results,
        }

        response = requests.post(
            SERPER_SEARCH_URL,
            headers=self.headers,
            data=json.dumps(payload),
        )

        response.raise_for_status()

        results = response.json()
        organic_results = results.get("organic") or []

        validated_results: list[WebSearchResult] = []
        for result in organic_results:
            link = (result.get("link") or "").strip()
            if not link:
                continue

            title = (result.get("title") or "").strip()
            snippet = (result.get("snippet") or "").strip()

            validated_results.append(
                WebSearchResult(
                    title=title,
                    link=link,
                    snippet=snippet,
                    author=None,
                    published_date=None,
                )
            )

        return validated_results

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
                    detail=f"Invalid Serper API key: {error_msg}",
                ) from e
            raise HTTPException(
                status_code=400,
                detail=f"Serper API key validation failed: {error_msg}",
            ) from e

        logger.info("Web search provider test succeeded for Serper.")
        return {"status": "ok"}

    def contents(self, urls: Sequence[str]) -> list[WebContent]:
        if not urls:
            return []

        # Serper can responds with 500s regularly. We want to retry,
        # but in the event of failure, return an unsuccesful scrape.
        def safe_get_webpage_content(url: str) -> WebContent:
            try:
                return self._get_webpage_content(url)
            except Exception:
                return WebContent(
                    title="",
                    link=url,
                    full_content="",
                    published_date=None,
                    scrape_successful=False,
                )

        with ThreadPoolExecutor(max_workers=min(8, len(urls))) as e:
            return list(e.map(safe_get_webpage_content, urls))

    @retry_builder(tries=3, delay=1, backoff=2)
    def _get_webpage_content(self, url: str) -> WebContent:
        payload = {
            "url": url,
        }

        response = requests.post(
            SERPER_CONTENTS_URL,
            headers=self.headers,
            data=json.dumps(payload),
        )

        # 400 returned when serper cannot scrape
        if response.status_code == 400:
            return WebContent(
                title="",
                link=url,
                full_content="",
                published_date=None,
                scrape_successful=False,
            )

        response.raise_for_status()

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

        return WebContent(
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
