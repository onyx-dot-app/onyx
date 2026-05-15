"""Tests for the failure-message construction in `open_url_tool`.

When a URL can't be fetched, the LLM-facing message should include each
URL's `failure_reason` so the model knows why and won't retry verbatim.
"""

from __future__ import annotations

from onyx.tools.tool_implementations.open_url.models import FailedFetch
from onyx.tools.tool_implementations.open_url.onyx_web_crawler import FailureReason
from onyx.tools.tool_implementations.open_url.open_url_tool import (
    _build_failure_message,
)
from onyx.tools.tool_implementations.open_url.open_url_tool import _format_failed_url


def test_format_failed_url_with_reason() -> None:
    failure = FailedFetch(url="https://x.com/", failure_reason="404 not found")
    assert _format_failed_url(failure) == "https://x.com/ (404 not found)"


def test_format_failed_url_without_reason() -> None:
    failure = FailedFetch(url="https://x.com/", failure_reason=None)
    assert _format_failed_url(failure) == "https://x.com/"


def test_failure_message_with_no_inputs_is_generic() -> None:
    msg = _build_failure_message(missing_document_ids=[], failed_web_fetches=[])
    assert msg == "Failed to fetch content from the requested resources."


def test_failure_message_includes_cloudflare_reason() -> None:
    """The whole point of #1: the LLM sees that this URL is bot-protected."""
    failure = FailedFetch(
        url="https://integrations.mindbodyonline.com/",
        failure_reason=FailureReason.CLOUDFLARE_CHALLENGE,
    )
    msg = _build_failure_message(missing_document_ids=[], failed_web_fetches=[failure])
    assert "https://integrations.mindbodyonline.com/" in msg
    assert "Cloudflare bot challenge" in msg
    assert "Firecrawl" in msg


def test_failure_message_dedupes_same_url() -> None:
    failures = [
        FailedFetch(url="https://x.com/", failure_reason="reason A"),
        FailedFetch(url="https://x.com/", failure_reason="reason B"),
    ]
    msg = _build_failure_message(missing_document_ids=[], failed_web_fetches=failures)
    # Should mention the URL once, with the first-seen reason.
    assert msg.count("https://x.com/") == 1
    assert "(reason A)" in msg


def test_failure_message_combines_documents_and_urls() -> None:
    failure = FailedFetch(
        url="https://x.com/", failure_reason="upstream returned HTTP 500"
    )
    msg = _build_failure_message(
        missing_document_ids=["doc-1", "doc-2"],
        failed_web_fetches=[failure],
    )
    # Sorted: doc-1, doc-2 / single URL.
    assert "documents doc-1, doc-2" in msg
    assert "URLs https://x.com/ (upstream returned HTTP 500)" in msg
    assert " and " in msg


def test_failure_message_skips_urls_with_blank_url_field() -> None:
    failures = [
        FailedFetch(url="", failure_reason="reason"),
        FailedFetch(url="https://real.com/", failure_reason="reason"),
    ]
    msg = _build_failure_message(missing_document_ids=[], failed_web_fetches=failures)
    assert "https://real.com/" in msg
    # Empty URL should not show up as ", ()" or similar oddity.
    assert msg.count("(reason)") == 1


def test_failure_message_url_without_reason_omits_parens() -> None:
    failure = FailedFetch(url="https://x.com/", failure_reason=None)
    msg = _build_failure_message(missing_document_ids=[], failed_web_fetches=[failure])
    assert "https://x.com/" in msg
    assert "(" not in msg


# ---------------------------------------------------------------------------
# CF challenge body detector — used by the OnyxWebCrawler fallback to decide
# whether a successful Playwright render actually contains the real page or
# just the CF interstitial.
# ---------------------------------------------------------------------------


def test_looks_like_cloudflare_challenge_detects_script_src() -> None:
    from onyx.utils.playwright_fetch import looks_like_cloudflare_challenge

    html = '<html><body><script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script></body></html>'
    assert looks_like_cloudflare_challenge(html)


def test_looks_like_cloudflare_challenge_detects_jschallenge_path() -> None:
    from onyx.utils.playwright_fetch import looks_like_cloudflare_challenge

    html = '<html><body><script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script></body></html>'
    assert looks_like_cloudflare_challenge(html)


def test_looks_like_cloudflare_challenge_detects_just_a_moment() -> None:
    from onyx.utils.playwright_fetch import looks_like_cloudflare_challenge

    html = "<html><head><title>Just a moment...</title></head></html>"
    assert looks_like_cloudflare_challenge(html)


def test_looks_like_cloudflare_challenge_detects_verifying_human_text() -> None:
    from onyx.utils.playwright_fetch import looks_like_cloudflare_challenge

    html = "<html><body>Verifying you are human. Please wait.</body></html>"
    assert looks_like_cloudflare_challenge(html)


def test_looks_like_cloudflare_challenge_is_false_for_real_page() -> None:
    from onyx.utils.playwright_fetch import looks_like_cloudflare_challenge

    html = "<html><head><title>Welcome</title></head><body><p>Real content here.</p></body></html>"
    assert not looks_like_cloudflare_challenge(html)


def test_looks_like_cloudflare_challenge_handles_empty_string() -> None:
    from onyx.utils.playwright_fetch import looks_like_cloudflare_challenge

    assert not looks_like_cloudflare_challenge("")
