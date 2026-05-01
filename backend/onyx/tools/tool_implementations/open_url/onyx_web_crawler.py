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
    # Generic 403 with no Cloudflare evidence. Kept distinct from
    # CLOUDFLARE_CHALLENGE so we don't tell the LLM to "configure Firecrawl"
    # for what's actually an auth wall, expired presigned URL, private repo, etc.
    HTTP_403_BLOCKED = (
        "upstream returned HTTP 403 — the URL likely requires authentication "
        "or is otherwise restricted from the built-in crawler"
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


def _has_cloudflare_signals(response: requests.Response) -> bool:
    """True iff the response carries actual Cloudflare-specific markers.

    Strict on purpose — only used to choose between the CF-specific failure
    reason (which tells admins to configure Firecrawl) vs. the generic 403
    failure reason (which points at auth / access). A bare 403 with no
    `cf-ray` / `cf-mitigated` / `Server: cloudflare` headers is treated
    as "not Cloudflare" here.
    """
    headers = response.headers
    if any(name in headers for name in _CLOUDFLARE_HEADER_NAMES):
        return True
    server = headers.get("Server", "").lower()
    return server.startswith("cloudflare")


def _should_try_playwright_fallback(response: requests.Response) -> bool:
    """True if a Playwright render is plausibly worth attempting.

    Broader than `_has_cloudflare_signals` — any 403 is cheap insurance to
    retry through a real browser (some sites serve JS-protected interstitials
    without CF headers). Real 401/404/410/5xx errors fall through unchanged.
    """
    return response.status_code >= 300 and (
        response.status_code == 403 or _has_cloudflare_signals(response)
    )


def _failure_reason_for_status(
    response: requests.Response, has_cf_signals: bool
) -> str:
    """Pick the LLM-facing failure reason for a 4xx/5xx upstream response.

    Only labels failures as Cloudflare when the response actually carries
    CF-specific headers — bare 403s without those headers are far more
    often auth walls or access-restricted resources, and labelling them
    "Cloudflare" sends the LLM and the admin chasing the wrong fix.
    """
    if has_cf_signals:
        return FailureReason.CLOUDFLARE_CHALLENGE
    if response.status_code == 403:
        return FailureReason.HTTP_403_BLOCKED
    return FailureReason.http_status(response.status_code)


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
            # Decide separately:
            #   - whether to attempt the Playwright fallback (broad, any 403
            #     is cheap insurance — some sites serve JS interstitials
            #     without CF-specific headers)
            #   - what failure reason to surface when nothing works (strict;
            #     only claim "Cloudflare" when we have actual CF evidence,
            #     either headers or a CF body returned by the render. A bare
            #     403 from e.g. a private GitHub repo or expired presigned
            #     S3 URL gets the generic-403 reason instead).
            has_cf_signals = _has_cloudflare_signals(response)
            try_fallback = (
                self._playwright_fallback_enabled
                and _should_try_playwright_fallback(response)
            )

            if try_fallback:
                logger.info(
                    "Onyx crawler got %s for %s; retrying via Playwright "
                    "(cf_signals=%s)",
                    response.status_code,
                    url,
                    has_cf_signals,
                )
                fallback = self._fetch_via_playwright(url)
                if fallback is not None:
                    # Either a successful render OR a definitive CF-challenge
                    # signal from the rendered body itself. Either way the
                    # fallback's own result is the truth.
                    return fallback

            logger.warning("Onyx crawler received %s for %s", response.status_code, url)
            return _failed_result(
                url, _failure_reason_for_status(response, has_cf_signals)
            )

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
            - Successful `WebContent` on success.
            - Failed `WebContent` with `failure_reason=CLOUDFLARE_CHALLENGE`
              when the render came back as the CF challenge interstitial
              itself (a definitive signal we can pass up regardless of what
              headers the original response carried).
            - `None` when the fallback gave us no new information (Chromium
              failed to launch, navigation hard-errored, content oversized,
              or rendered HTML didn't parse to anything). Caller should fall
              back to its own status-based failure reason.
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

        # If the render came back as a CF challenge interstitial, surface
        # that as a definitive CF failure (parsing it would just leak
        # "Just a moment..." text to the LLM). This is the one case where
        # Playwright actually adds information vs. the original 4xx.
        if looks_like_cloudflare_challenge(rendered.html):
            logger.info(
                "Playwright fallback rendered the Cloudflare challenge page "
                "itself for %s; treating as Cloudflare failure",
                url,
            )
            return _failed_result(url, FailureReason.CLOUDFLARE_CHALLENGE)

        result = _parse_html_to_web_content(url, rendered.html)
        if not result.scrape_successful:
            return None
        logger.info("Playwright fallback succeeded for %s", url)
        return result
