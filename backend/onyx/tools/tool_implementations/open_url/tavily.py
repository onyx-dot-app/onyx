from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import requests

from onyx.tools.tool_implementations.open_url.models import WebContent
from onyx.tools.tool_implementations.open_url.models import WebContentProvider
from onyx.utils.logger import setup_logger

logger = setup_logger()

TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"
TAVILY_EXTRACT_MAX_URLS = 20
_DEFAULT_TIMEOUT_SECONDS = 55


class TavilyExtractClient(WebContentProvider):
    def __init__(
        self,
        api_key: str,
        *,
        timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._last_error: str | None = None

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def contents(self, urls: Sequence[str]) -> list[WebContent]:
        if not urls:
            return []

        # Tavily Extract accepts up to 20 URLs per request — batch if needed
        all_results: list[WebContent] = []
        for i in range(0, len(urls), TAVILY_EXTRACT_MAX_URLS):
            batch = list(urls[i : i + TAVILY_EXTRACT_MAX_URLS])
            all_results.extend(self._extract_batch(batch))
        return all_results

    def _extract_batch(self, urls: list[str]) -> list[WebContent]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "urls": urls,
            "format": "markdown",
        }

        try:
            response = requests.post(
                TAVILY_EXTRACT_URL,
                headers=headers,
                json=body,
                timeout=self._timeout_seconds,
            )
        except requests.RequestException as exc:
            self._last_error = str(exc)
            return [
                WebContent(
                    title="",
                    link=url,
                    full_content="",
                    scrape_successful=False,
                )
                for url in urls
            ]

        if response.status_code != 200:
            error_detail = _extract_error_detail(response)
            self._last_error = error_detail

            if 400 <= response.status_code < 500:
                return [
                    WebContent(
                        title="",
                        link=url,
                        full_content="",
                        scrape_successful=False,
                    )
                    for url in urls
                ]

            raise ValueError(
                f"Tavily extract failed with status {response.status_code}: {error_detail}"
            )

        self._last_error = None
        data = response.json()

        results: list[WebContent] = []

        # Process successful results
        for item in data.get("results") or []:
            if not isinstance(item, dict):
                continue
            url = item.get("url", "")
            raw_content = item.get("raw_content", "")
            results.append(
                WebContent(
                    title="",
                    link=url,
                    full_content=raw_content,
                    scrape_successful=bool(raw_content),
                )
            )

        # Process failed results
        for item in data.get("failed_results") or []:
            if not isinstance(item, dict):
                continue
            url = item.get("url", "")
            error = item.get("error", "Unknown error")
            logger.warning("Tavily extract failed for url=%s: %s", url, error)
            results.append(
                WebContent(
                    title="",
                    link=url,
                    full_content="",
                    scrape_successful=False,
                )
            )

        return results


def _extract_error_detail(response: requests.Response) -> str:
    try:
        payload: Any = response.json()
    except Exception:
        text = response.text.strip()
        return text[:200] if text else "No error details"

    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("message") or payload.get("error")
        if isinstance(detail, str):
            return detail

    return str(payload)[:200]
