from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

import requests

from onyx.agents.agent_search.dr.sub_agents.web_search.models import WebContent
from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
    WebContentProvider,
)
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()

FIRECRAWL_SCRAPE_URL = "https://api.firecrawl.dev/v1/scrape"
_DEFAULT_MAX_WORKERS = 4


class FirecrawlClient(WebContentProvider):
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = FIRECRAWL_SCRAPE_URL,
        timeout_seconds: int = 30,
    ) -> None:

        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds
        self._last_error: str | None = None

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def contents(self, urls: Sequence[str]) -> list[WebContent]:
        if not urls:
            return []

        max_workers = min(_DEFAULT_MAX_WORKERS, len(urls))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            return list(executor.map(self._get_webpage_content_safe, urls))

    def _get_webpage_content_safe(self, url: str) -> WebContent:
        try:
            return self._get_webpage_content(url)
        except Exception as exc:
            self._last_error = str(exc)
            return WebContent(
                title="",
                link=url,
                full_content="",
                published_date=None,
                scrape_successful=False,
            )

    @retry_builder(tries=3, delay=1, backoff=2)
    def _get_webpage_content(self, url: str) -> WebContent:
        payload = {
            "url": url,
            "formats": ["markdown"],
        }

        response = requests.post(
            self._base_url,
            headers=self._headers,
            json=payload,
            timeout=self._timeout_seconds,
        )

        if response.status_code != 200:
            try:
                error_payload = response.json()
            except Exception:
                error_payload = response.text
            self._last_error = (
                error_payload if isinstance(error_payload, str) else str(error_payload)
            )

            if 400 <= response.status_code < 500:
                return WebContent(
                    title="",
                    link=url,
                    full_content="",
                    published_date=None,
                    scrape_successful=False,
                )

            raise ValueError(
                f"Firecrawl fetch failed with status {response.status_code}."
            )
        else:
            self._last_error = None

        response_json = response.json()
        text, title, published_date = self._extract_content_fields(response_json, url)

        return WebContent(
            title=title,
            link=url,
            full_content=text,
            published_date=published_date,
            scrape_successful=bool(text),
        )

    @staticmethod
    def _extract_content_fields(
        response_json: dict[str, Any], url: str
    ) -> tuple[str, str, datetime | None]:
        data_section = response_json.get("data") or {}
        metadata = data_section.get("metadata") or response_json.get("metadata") or {}

        text_candidates = [
            data_section.get("markdown"),
            data_section.get("content"),
            data_section.get("text"),
            response_json.get("markdown"),
            response_json.get("content"),
            response_json.get("text"),
        ]

        text = next((candidate for candidate in text_candidates if candidate), "")
        title = metadata.get("title") or response_json.get("title") or ""
        published_date = None

        published_date_str = (
            metadata.get("publishedTime")
            or metadata.get("date")
            or response_json.get("publishedTime")
            or response_json.get("date")
        )

        if published_date_str:
            try:
                published_date = time_str_to_utc(published_date_str)
            except Exception:
                published_date = None

        if not text:
            logger.warning(f"Firecrawl returned empty content for url={url}")

        return text or "", title or "", published_date
