from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor

import requests

from onyx.configs.app_configs import OPEN_URL_PLAYWRIGHT_FALLBACK_ENABLED
from onyx.file_processing.html_utils import ParsedHTML
from onyx.file_processing.html_utils import web_html_cleanup
from onyx.tools.tool_implementations.open_url.models import WebContent
from onyx.tools.tool_implementations.open_url.models import WebContentProvider
from onyx.utils.logger import setup_logger
from onyx.utils.playwright_fetch import fetch_rendered_html
from onyx.utils.playwright_fetch import looks_like_cloudflare_challenge
from onyx.utils.playwright_fetch import RenderedPage
from onyx.utils.url import ssrf_safe_get
from onyx.utils.url import SSRFException
from onyx.utils.web_content import decode_html_bytes
from onyx.utils.web_content import extract_pdf_text
from onyx.utils.web_content import is_pdf_resource
from onyx.utils.web_content import title_from_pdf_metadata
from onyx.utils.web_content import title_from_url

logger = setup_logger()

DEFAULT_READ_TIMEOUT_SECONDS = 15
DEFAULT_CONNECT_TIMEOUT_SECONDS = 5
DEFAULT_USER_AGENT = "OnyxWebCrawler/1.0 (+https://www.onyx.app)"
DEFAULT_MAX_PDF_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB
DEFAULT_MAX_HTML_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB
DEFAULT_MAX_WORKERS = 5

# Headers that, when present on a 4xx response, signal that the upstream
# is a Cloudflare-style bot challenge (vs. a real auth/not-found error)
# and that retrying via a headless browser is likely to succeed.
_CLOUDFLARE_HEADER_NAMES = ("cf-ray", "cf-mitigated")


# Failure-reason strings surfaced to the LLM. Centralized so we don't drift
# wording across call sites and so the LLM sees consistent text to reason
# over (e.g. "don't bother retrying this URL").
class FailureReason:
    CLOUDFLARE_CHALLENGE = (
        "blocked by a Cloudflare bot challenge that the built-in crawler "
        "cannot solve — try a different URL or configure Firecrawl as the "
        "web content provider"
    )
    SSRF_BLOCKED = "blocked by SSRF protection (URL resolves to an internal address)"
    NETWORK_ERROR = "network error while fetching the URL"
    OVERSIZED_HTML = "HTML response exceeded the configured maximum size"
    OVERSIZED_PDF = "PDF response exceeded the configured maximum size"
    DECODE_ERROR = "could not decode the response body"
    EMPTY_OR_UNPARSEABLE = "response could not be parsed into readable text"

    @staticmethod
    def http_status(status_code: int) -> str:
        return f"upstream returned HTTP {status_code}"


def _failed_result(url: str, failure_reason: str | None = None) -> WebContent:
    return WebContent(
        title="",
        link=url,
        full_content="",
        published_date=None,
        scrape_successful=False,
        failure_reason=failure_reason,
    )


def _looks_like_bot_challenge_response(response: requests.Response) -> bool:
    """True if a non-2xx response looks like a Cloudflare/bot-management challenge.

    Conservative on purpose: we want to spend Chromium time (and emit
    "Cloudflare blocked us" failure reasons) only on responses that actually
    look like CF challenges, not on real 401/404/410/etc. errors.
    """
    if response.status_code == 403:
        return True
    headers = response.headers
    if any(name in headers for name in _CLOUDFLARE_HEADER_NAMES):
        return True
    server = headers.get("Server", "").lower()
    return server.startswith("cloudflare")


def _parse_html_to_web_content(url: str, html: str) -> WebContent:
    """Run cleanup on raw HTML and shape the result into a WebContent.

    Used by both the fast `requests` path and the Playwright fallback, so
    they emit identical-shape results.
    """
    try:
        parsed: ParsedHTML = web_html_cleanup(html)
        text_content = parsed.cleaned_text or ""
        title = parsed.title or ""
    except Exception as exc:
        logger.warning(
            "Onyx crawler failed to parse %s (%s)", url, exc.__class__.__name__
        )
        return _failed_result(url, FailureReason.EMPTY_OR_UNPARSEABLE)

    if not text_content.strip():
        return _failed_result(url, FailureReason.EMPTY_OR_UNPARSEABLE)

    return WebContent(
        title=title,
        link=url,
        full_content=text_content,
        published_date=None,
        scrape_successful=True,
    )


class OnyxWebCrawler(WebContentProvider):
    """
    Lightweight built-in crawler that fetches HTML directly and extracts readable text.
    Acts as the default content provider when no external crawler (e.g. Firecrawl) is
    configured.

    On a Cloudflare/bot-challenge response (canonical entry point: HTTP 403,
    or any response carrying a `cf-ray` / `cf-mitigated` header), falls back
    to a one-shot headless-browser fetch via `playwright_fetch`. Controlled
    by the `OPEN_URL_PLAYWRIGHT_FALLBACK_ENABLED` flag.
    """

    def __init__(
        self,
        *,
        timeout_seconds: int = DEFAULT_READ_TIMEOUT_SECONDS,
        connect_timeout_seconds: int = DEFAULT_CONNECT_TIMEOUT_SECONDS,
        user_agent: str = DEFAULT_USER_AGENT,
        max_pdf_size_bytes: int | None = None,
        max_html_size_bytes: int | None = None,
        playwright_fallback_enabled: bool = OPEN_URL_PLAYWRIGHT_FALLBACK_ENABLED,
    ) -> None:
        self._read_timeout_seconds = timeout_seconds
        self._connect_timeout_seconds = connect_timeout_seconds
        self._max_pdf_size_bytes = max_pdf_size_bytes
        self._max_html_size_bytes = max_html_size_bytes
        self._playwright_fallback_enabled = playwright_fallback_enabled
        self._headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

    def contents(self, urls: Sequence[str]) -> list[WebContent]:
        if not urls:
            return []

        max_workers = min(DEFAULT_MAX_WORKERS, len(urls))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            return list(executor.map(self._fetch_url_safe, urls))

    def _fetch_url_safe(self, url: str) -> WebContent:
        """Wrapper that catches all exceptions so one bad URL doesn't kill the batch."""
        try:
            return self._fetch_url(url)
        except Exception as exc:
            logger.warning(
                "Onyx crawler unexpected error for %s (%s)",
                url,
                exc.__class__.__name__,
            )
            return _failed_result(url, FailureReason.NETWORK_ERROR)

    def _fetch_url(self, url: str) -> WebContent:
        try:
            response = ssrf_safe_get(
                url,
                headers=self._headers,
                timeout=(self._connect_timeout_seconds, self._read_timeout_seconds),
            )
        except SSRFException as exc:
            logger.error(
                "SSRF protection blocked request to %s (%s)",
                url,
                exc.__class__.__name__,
            )
            return _failed_result(url, FailureReason.SSRF_BLOCKED)
        except Exception as exc:
            logger.warning(
                "Onyx crawler failed to fetch %s (%s)",
                url,
                exc.__class__.__name__,
            )
            return _failed_result(url, FailureReason.NETWORK_ERROR)

        if response.status_code >= 400:
            cf_challenge_suspected = _looks_like_bot_challenge_response(response)
            if cf_challenge_suspected and self._playwright_fallback_enabled:
                logger.info(
                    "Onyx crawler got %s for %s with bot-challenge signals; "
                    "retrying via Playwright",
                    response.status_code,
                    url,
                )
                fallback = self._fetch_via_playwright(url)
                if fallback is not None:
                    return fallback
                # Playwright path either failed to render or came back with the
                # challenge body itself — surface a CF-specific failure reason
                # so the LLM stops retrying and the admin knows what to fix.
                logger.warning(
                    "Onyx crawler could not bypass Cloudflare challenge for %s",
                    url,
                )
                return _failed_result(url, FailureReason.CLOUDFLARE_CHALLENGE)

            logger.warning("Onyx crawler received %s for %s", response.status_code, url)
            reason = (
                FailureReason.CLOUDFLARE_CHALLENGE
                if cf_challenge_suspected
                else FailureReason.http_status(response.status_code)
            )
            return _failed_result(url, reason)

        content_type = response.headers.get("Content-Type", "")
        content = response.content

        content_sniff = content[:1024] if content else None
        if is_pdf_resource(url, content_type, content_sniff):
            return self._handle_pdf_response(url, content)

        if (
            self._max_html_size_bytes is not None
            and len(content) > self._max_html_size_bytes
        ):
            logger.warning(
                "HTML content too large (%d bytes) for %s, max is %d",
                len(content),
                url,
                self._max_html_size_bytes,
            )
            return _failed_result(url, FailureReason.OVERSIZED_HTML)

        try:
            decoded_html = decode_html_bytes(
                content,
                content_type=content_type,
                fallback_encoding=response.apparent_encoding or response.encoding,
            )
        except Exception as exc:
            logger.warning(
                "Onyx crawler failed to decode %s (%s)", url, exc.__class__.__name__
            )
            return _failed_result(url, FailureReason.DECODE_ERROR)

        return _parse_html_to_web_content(url, decoded_html)

    def _handle_pdf_response(self, url: str, content: bytes) -> WebContent:
        if (
            self._max_pdf_size_bytes is not None
            and len(content) > self._max_pdf_size_bytes
        ):
            logger.warning(
                "PDF content too large (%d bytes) for %s, max is %d",
                len(content),
                url,
                self._max_pdf_size_bytes,
            )
            return _failed_result(url, FailureReason.OVERSIZED_PDF)
        text_content, metadata = extract_pdf_text(content)
        title = title_from_pdf_metadata(metadata) or title_from_url(url)
        if not text_content.strip():
            return _failed_result(url, FailureReason.EMPTY_OR_UNPARSEABLE)
        return WebContent(
            title=title,
            link=url,
            full_content=text_content,
            published_date=None,
            scrape_successful=True,
        )

    def _fetch_via_playwright(self, url: str) -> WebContent | None:
        """Try a one-shot headless render.

        Returns:
            WebContent on success.
            None when the fallback didn't help (browser failed to launch,
            CF challenge page came back, or content was empty/oversized).
            The caller decides what failure_reason to surface in that case.
        """
        rendered: RenderedPage | None = fetch_rendered_html(url)
        if rendered is None:
            return None

        if (
            self._max_html_size_bytes is not None
            and len(rendered.html) > self._max_html_size_bytes
        ):
            logger.warning(
                "Rendered HTML too large (%d chars) for %s, max is %d",
                len(rendered.html),
                url,
                self._max_html_size_bytes,
            )
            return None

        # If the render came back as a CF challenge interstitial itself,
        # don't return it — it parses to "Just a moment..." or similar
        # garbage that would mislead the LLM into thinking it had real
        # content. Caller will surface the CLOUDFLARE_CHALLENGE reason.
        if looks_like_cloudflare_challenge(rendered.html):
            logger.info(
                "Playwright fallback rendered the Cloudflare challenge page "
                "itself for %s; treating as failure",
                url,
            )
            return None

        result = _parse_html_to_web_content(url, rendered.html)
        if not result.scrape_successful:
            return None
        logger.info("Playwright fallback succeeded for %s", url)
        return result
