from __future__ import annotations

from onyx.tools.tool_implementations.open_url.models import FailedFetch
from onyx.tools.tool_implementations.open_url.open_url_tool import (
    _build_search_snippet_fallback_sections,
)
from onyx.tools.tool_implementations.web_search.models import WebSearchResult
from onyx.tools.tool_implementations.web_search.utils import (
    inference_section_from_internet_search_result,
)


def test_failed_url_with_search_snippet_gets_fallback_section() -> None:
    url = "https://example.com/report"

    sections, failures = _build_search_snippet_fallback_sections(
        urls=[url],
        existing_sections=[],
        failed_web_fetches=[
            FailedFetch(url=url, failure_reason="blocked by bot protection")
        ],
        url_snippet_map={url: "Important search evidence from Tavily raw content."},
    )

    assert failures == []
    assert len(sections) == 1
    section = sections[0]
    assert section.center_chunk.source_links[0] == url
    assert "recent web_search snippet fallback" in section.combined_content
    assert "not full page content" in section.combined_content
    assert "Important search evidence" in section.combined_content


def test_existing_successful_section_prevents_duplicate_snippet_fallback() -> None:
    url = "https://example.com/report"
    existing_section = inference_section_from_internet_search_result(
        WebSearchResult(
            title="Fetched page",
            link=url,
            snippet="Real fetched content.",
        )
    )

    sections, failures = _build_search_snippet_fallback_sections(
        urls=[url],
        existing_sections=[existing_section],
        failed_web_fetches=[
            FailedFetch(url=url, failure_reason="stale failed crawler result")
        ],
        url_snippet_map={url: "Snippet should not be used."},
    )

    assert sections == []
    assert failures == [
        FailedFetch(url=url, failure_reason="stale failed crawler result")
    ]


def test_fallback_matches_normalized_search_result_urls() -> None:
    requested_url = "https://example.com/report?utm_source=test"
    normalized_url = "https://example.com/report"

    sections, failures = _build_search_snippet_fallback_sections(
        urls=[requested_url],
        existing_sections=[],
        failed_web_fetches=[
            FailedFetch(url=normalized_url, failure_reason="request timed out")
        ],
        url_snippet_map={normalized_url: "Snippet keyed by normalized result URL."},
    )

    assert failures == []
    assert len(sections) == 1
    assert sections[0].center_chunk.source_links[0] == normalized_url
    assert "Snippet keyed by normalized result URL" in sections[0].combined_content
