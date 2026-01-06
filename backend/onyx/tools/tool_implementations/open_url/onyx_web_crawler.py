from __future__ import annotations

import io
from collections.abc import Sequence
from urllib.parse import unquote
from urllib.parse import urlparse

from onyx.file_processing.extract_file_text import read_pdf_file
from onyx.file_processing.file_types import PDF_MIME_TYPE
from onyx.file_processing.html_utils import ParsedHTML
from onyx.file_processing.html_utils import web_html_cleanup
from onyx.tools.tool_implementations.open_url.models import (
    WebContent,
)
from onyx.tools.tool_implementations.open_url.models import (
    WebContentProvider,
)
from onyx.utils.logger import setup_logger
from onyx.utils.url import ssrf_safe_get
from onyx.utils.url import SSRFException

logger = setup_logger()

DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_USER_AGENT = "OnyxWebCrawler/1.0 (+https://www.onyx.app)"


class OnyxWebCrawler(WebContentProvider):
    """
    Lightweight built-in crawler that fetches HTML directly and extracts readable text.
    Acts as the default content provider when no external crawler (e.g. Firecrawl) is
    configured.
    """

    def __init__(
        self,
        *,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

    def contents(self, urls: Sequence[str]) -> list[WebContent]:
        results: list[WebContent] = []
        for url in urls:
            results.append(self._fetch_url(url))
        return results

    def _fetch_url(self, url: str) -> WebContent:
        try:
            # Use SSRF-safe request to prevent DNS rebinding attacks
            response = ssrf_safe_get(
                url, headers=self._headers, timeout=self._timeout_seconds
            )
        except SSRFException as exc:
            logger.error(
                "SSRF protection blocked request to %s: %s",
                url,
                str(exc),
            )
            return WebContent(
                title="",
                link=url,
                full_content="",
                published_date=None,
                scrape_successful=False,
            )
        except Exception as exc:  # pragma: no cover - network failures vary
            logger.warning(
                "Onyx crawler failed to fetch %s (%s)",
                url,
                exc.__class__.__name__,
            )
            return WebContent(
                title="",
                link=url,
                full_content="",
                published_date=None,
                scrape_successful=False,
            )

        if response.status_code >= 400:
            logger.warning("Onyx crawler received %s for %s", response.status_code, url)
            return WebContent(
                title="",
                link=url,
                full_content="",
                published_date=None,
                scrape_successful=False,
            )

        if self._is_pdf_response(response, url):
            text_content, title = self._extract_pdf_text(response, url)
            return WebContent(
                title=title,
                link=url,
                full_content=text_content,
                published_date=None,
                scrape_successful=bool(text_content.strip()),
            )

        try:
            parsed: ParsedHTML = web_html_cleanup(response.text)
            text_content = parsed.cleaned_text or ""
            title = parsed.title or ""
        except Exception as exc:
            logger.warning(
                "Onyx crawler failed to parse %s (%s)", url, exc.__class__.__name__
            )
            text_content = ""
            title = ""

        return WebContent(
            title=title,
            link=url,
            full_content=text_content,
            published_date=None,
            scrape_successful=bool(text_content.strip()),
        )

    def _is_pdf_response(self, response: object, url: str) -> bool:
        content_type = ""
        if hasattr(response, "headers"):
            content_type = response.headers.get("Content-Type", "")
        media_type = content_type.split(";", 1)[0].strip().lower()
        if media_type == PDF_MIME_TYPE:
            return True

        parsed_url = urlparse(url)
        if parsed_url.path.lower().endswith(".pdf"):
            return True

        if hasattr(response, "content"):
            content = response.content
            snippet = content[:1024].lstrip()
            if snippet.startswith(b"%PDF-"):
                return True

        return False

    def _extract_pdf_text(self, response: object, url: str) -> tuple[str, str]:
        pdf_bytes = response.content if hasattr(response, "content") else b""
        text_content, metadata, _ = read_pdf_file(io.BytesIO(pdf_bytes))
        title = self._pdf_title(metadata) or self._title_from_url(url)
        return text_content or "", title

    @staticmethod
    def _pdf_title(metadata: dict[str, object]) -> str:
        if not metadata:
            return ""
        for key in ("Title", "title"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _title_from_url(url: str) -> str:
        parsed = urlparse(url)
        filename = parsed.path.rsplit("/", 1)[-1]
        if not filename:
            return ""
        return unquote(filename)
