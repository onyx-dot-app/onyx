from __future__ import annotations

import html
import re
from collections.abc import Sequence

from onyx.context.search.utils import remove_stop_words_and_punctuation
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
from onyx.utils.web_content import decode_html_bytes
from onyx.utils.web_content import extract_pdf_text
from onyx.utils.web_content import is_pdf_resource
from onyx.utils.web_content import title_from_pdf_metadata
from onyx.utils.web_content import title_from_url

logger = setup_logger()

DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_USER_AGENT = "OnyxWebCrawler/1.0 (+https://www.onyx.app)"

# Content limiting constants
MAX_HTML_BYTES = 2_000_000  # 2MB max raw HTML to prevent memory exhaustion
MAX_TOTAL_CONTENT_CHARS = 200_000  # Max total chars in final output (~50K tokens)

# Context window around keyword matches (~10K tokens = ~40K chars)
CONTEXT_CHARS_PER_MATCH = 40_000

# Splice marker when content is omitted
SPLICE_MARKER = (
    "\n\n[... content omitted - showing sections relevant to your query ...]\n\n"
)
TRUNCATION_MARKER = "\n\n[... content truncated ({omitted} chars omitted) ...]"


class OnyxWebCrawler(WebContentProvider):
    """
    Lightweight built-in crawler that fetches HTML directly and extracts readable text.
    Acts as the default content provider when no external crawler (e.g. Firecrawl) is
    configured.

    Supports relevance-based content extraction when a query is provided, using a
    two-pass approach: first scan for keyword positions, then only parse relevant regions.
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

    def contents(
        self, urls: Sequence[str], query: str | None = None
    ) -> list[WebContent]:
        results: list[WebContent] = []
        for url in urls:
            results.append(self._fetch_url(url, query=query))
        return results

    def _fetch_url(self, url: str, query: str | None = None) -> WebContent:
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

        content_type = response.headers.get("Content-Type", "")
        content_sniff = response.content[:1024] if response.content else None
        if is_pdf_resource(url, content_type, content_sniff):
            text_content, metadata = extract_pdf_text(response.content)
            title = title_from_pdf_metadata(metadata) or title_from_url(url)
            return WebContent(
                title=title,
                link=url,
                full_content=text_content,
                published_date=None,
                scrape_successful=bool(text_content.strip()),
            )

        # Extract content with relevance filtering if query provided
        try:
            title, text_content = self._extract_relevant_content(
                response.content,
                content_type=content_type,
                fallback_encoding=response.apparent_encoding or response.encoding,
                query=query,
                url=url,
            )
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

    def _extract_relevant_content(
        self,
        html_bytes: bytes,
        content_type: str,
        fallback_encoding: str | None,
        query: str | None,
        url: str,
    ) -> tuple[str, str]:
        """Extract content from HTML, filtering by relevance if query provided.

        Uses a two-pass approach for large pages:
        1. Fast regex scan of decoded HTML to find keyword match positions
        2. Only parse regions around matches with BeautifulSoup

        This avoids parsing the entire DOM for large pages.

        Returns:
            Tuple of (title, text_content)
        """
        # Limit raw HTML size
        html_bytes = html_bytes[:MAX_HTML_BYTES]

        # Decode HTML once (this is cheap compared to BeautifulSoup parsing)
        try:
            html_str = decode_html_bytes(
                html_bytes,
                content_type=content_type,
                fallback_encoding=fallback_encoding,
            )
        except Exception as e:
            logger.debug(
                f"decode_html_bytes failed for {url}, falling back to UTF-8: {e}"
            )
            html_str = html_bytes.decode("utf-8", errors="ignore")

        # If page is small enough or no query, just parse normally
        if len(html_str) <= CONTEXT_CHARS_PER_MATCH or not query:
            logger.debug(
                f"Page small ({len(html_str)} chars) or no query, "
                f"using simple extraction: {url}"
            )
            return self._simple_extract(html_str)

        # Extract keywords from query using existing NLTK-based stopword removal
        keywords = self._extract_keywords(query)
        if not keywords:
            return self._simple_extract(html_str)

        # Pass 1: Fast regex scan to find keyword positions in the HTML
        match_positions = self._find_keyword_positions(html_str, keywords)

        if not match_positions:
            # No matches found, fall back to simple extraction (truncated)
            logger.info(f"No keyword matches found, using simple extraction: {url}")
            return self._simple_extract(html_str)

        logger.info(
            f"Found {len(match_positions)} keyword matches in {len(html_str)} char page, "
            f"extracting relevant regions: {url}"
        )

        # Expand match positions to include context and merge overlapping regions
        regions = self._expand_and_merge_regions(
            match_positions, len(html_str), CONTEXT_CHARS_PER_MATCH
        )

        logger.info(f"Merged into {len(regions)} regions to parse: {url}")

        # Pass 2: Only parse the identified regions
        title = ""
        relevant_texts: list[str] = []
        total_chars = 0

        for start, end in regions:
            if total_chars >= MAX_TOTAL_CONTENT_CHARS:
                break

            # Note: Slicing by character position may create malformed HTML fragments
            # (e.g., splitting mid-tag). This is intentional - BeautifulSoup handles
            # malformed HTML gracefully, and the alternative (parsing full HTML first)
            # defeats the memory optimization purpose of this two-pass approach.
            region_html = html_str[start:end]

            try:
                parsed: ParsedHTML = web_html_cleanup(region_html)
                region_text = parsed.cleaned_text or ""

                # Capture title from first region that has one
                if not title and parsed.title:
                    title = parsed.title
            except Exception as e:
                logger.warning(f"Failed to parse region [{start}:{end}] for {url}: {e}")
                continue

            if region_text:
                # Truncate if it would exceed our limit
                remaining_budget = MAX_TOTAL_CONTENT_CHARS - total_chars
                if len(region_text) > remaining_budget:
                    region_text = region_text[:remaining_budget]

                relevant_texts.append(region_text)
                total_chars += len(region_text)

        if not relevant_texts:
            # Fallback if parsing failed
            return self._simple_extract(html_str)

        # Join regions with splice marker if we have multiple non-contiguous regions
        if len(regions) > 1:
            text_content = SPLICE_MARKER.join(relevant_texts)
        else:
            text_content = relevant_texts[0] if relevant_texts else ""

        # If we didn't get a title from regions, try to extract from <title> tag
        if not title:
            title = self._extract_title_fast(html_str)

        return title, text_content

    def _simple_extract(self, html_str: str) -> tuple[str, str]:
        """Simple extraction: parse entire HTML at once."""
        parsed: ParsedHTML = web_html_cleanup(html_str)
        text_content = parsed.cleaned_text or ""
        title = parsed.title or ""

        # Apply final truncation if still too long
        if len(text_content) > MAX_TOTAL_CONTENT_CHARS:
            omitted = len(text_content) - MAX_TOTAL_CONTENT_CHARS
            text_content = text_content[
                :MAX_TOTAL_CONTENT_CHARS
            ] + TRUNCATION_MARKER.format(omitted=omitted)

        return title, text_content

    def _extract_keywords(self, query: str) -> list[str]:
        """Extract significant keywords from query for relevance matching.

        Uses the existing NLTK-based stopword removal from onyx.context.search.utils.
        """
        # Split query into words (handles Unicode properly)
        words = query.split()
        words = [w for w in words if w]  # Remove empty strings

        if not words:
            return []

        # Use existing NLTK stopword removal
        keywords = remove_stop_words_and_punctuation(words)

        # Filter out very short words (likely not meaningful) and lowercase
        keywords = [w.lower() for w in keywords if len(w) > 2]

        return keywords

    def _find_keyword_positions(self, html_str: str, keywords: list[str]) -> list[int]:
        """Find all positions where keywords appear in the HTML string.

        Uses word boundary matching to avoid partial matches (e.g., "cat" in "category").

        Returns a list of character positions where matches were found.
        """
        positions: list[int] = []
        html_lower = html_str.lower()

        for keyword in keywords:
            # Use word boundaries to match whole words only
            pattern = r"\b" + re.escape(keyword) + r"\b"
            for match in re.finditer(pattern, html_lower):
                positions.append(match.start())

        # Sort and dedupe positions
        return sorted(set(positions))

    def _expand_and_merge_regions(
        self,
        positions: list[int],
        total_length: int,
        context_size: int,
    ) -> list[tuple[int, int]]:
        """Expand match positions to include context and merge overlapping regions.

        Args:
            positions: Sorted list of match positions
            total_length: Total length of the HTML string
            context_size: Number of chars to include around each match

        Returns:
            List of (start, end) tuples representing non-overlapping regions
        """
        if not positions:
            return []

        half_context = context_size // 2
        regions: list[tuple[int, int]] = []

        for pos in positions:
            start = max(0, pos - half_context)
            end = min(total_length, pos + half_context)
            regions.append((start, end))

        # Merge overlapping regions
        merged: list[tuple[int, int]] = []
        for start, end in sorted(regions):
            if merged and start <= merged[-1][1]:
                # Overlaps with previous region, extend it
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))

        return merged

    def _extract_title_fast(self, html_str: str) -> str:
        """Extract title from HTML using regex (fast, no full parse)."""
        match = re.search(
            r"<title[^>]*>(.*?)</title>", html_str, re.IGNORECASE | re.DOTALL
        )
        if match:
            title = match.group(1).strip()
            title = re.sub(r"<[^>]+>", "", title)  # Remove any nested tags
            title = html.unescape(title)  # Decode all HTML entities
            return title.strip()
        return ""
