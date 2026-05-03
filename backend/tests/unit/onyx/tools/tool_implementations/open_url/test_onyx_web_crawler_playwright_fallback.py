"""Tests for OnyxWebCrawler's Playwright fallback on Cloudflare/bot challenges.

The fallback is triggered when the fast `requests` path returns a response
that looks like a Cloudflare challenge (HTTP 403, or any 4xx with `cf-ray`
/ `cf-mitigated` headers, or `Server: cloudflare`). On hit, we try a
one-shot headless render and re-parse.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

import onyx.tools.tool_implementations.open_url.onyx_web_crawler as crawler_module
from onyx.tools.tool_implementations.open_url.onyx_web_crawler import FailureReason
from onyx.tools.tool_implementations.open_url.onyx_web_crawler import OnyxWebCrawler
from onyx.utils.playwright_fetch import RenderedPage

SUCCESS_HTML = "<html><head><title>Real Page</title></head><body><p>Hello world, this is real content from the page after rendering.</p></body></html>"
# Empty rendered page — what we'd get if Playwright navigation produced nothing
# parseable (e.g. CF challenge hung past our grace period and was never replaced).
EMPTY_HTML = "<html><body></body></html>"
# Realistic-ish CF challenge interstitial. The marker that triggers detection
# is the script src referencing `challenges.cloudflare.com`.
CF_CHALLENGE_HTML = """<html>
<head><title>Just a moment...</title></head>
<body>
<script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script>
<p>Verifying you are human. This may take a few seconds.</p>
</body></html>"""


def _mock_response(
    *,
    status_code: int,
    headers: dict[str, str] | None = None,
    content: bytes = b"",
    content_type: str = "text/html",
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    merged_headers = {"Content-Type": content_type, **(headers or {})}
    resp.headers = merged_headers
    resp.content = content
    resp.apparent_encoding = None
    resp.encoding = None
    return resp


def _ok_rendered() -> RenderedPage:
    return RenderedPage(
        html=SUCCESS_HTML,
        final_url="https://example.com/",
        last_modified=None,
        status=200,
    )


# ---------------------------------------------------------------------------
# Fallback-trigger tests: which responses cause us to invoke Playwright?
# ---------------------------------------------------------------------------


@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.fetch_rendered_html")
@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.ssrf_safe_get")
def test_403_triggers_playwright_fallback(
    mock_get: MagicMock, mock_render: MagicMock
) -> None:
    mock_get.return_value = _mock_response(status_code=403)
    mock_render.return_value = _ok_rendered()

    result = OnyxWebCrawler()._fetch_url("https://example.com/")

    mock_render.assert_called_once_with("https://example.com/")
    assert result.scrape_successful
    assert "Hello world" in result.full_content
    assert result.title == "Real Page"


@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.fetch_rendered_html")
@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.ssrf_safe_get")
def test_4xx_with_cf_ray_triggers_playwright_fallback(
    mock_get: MagicMock, mock_render: MagicMock
) -> None:
    mock_get.return_value = _mock_response(
        status_code=429, headers={"cf-ray": "9f4994882a46eb36-SJC"}
    )
    mock_render.return_value = _ok_rendered()

    result = OnyxWebCrawler()._fetch_url("https://example.com/")

    mock_render.assert_called_once()
    assert result.scrape_successful


@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.fetch_rendered_html")
@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.ssrf_safe_get")
def test_4xx_with_cf_mitigated_triggers_playwright_fallback(
    mock_get: MagicMock, mock_render: MagicMock
) -> None:
    mock_get.return_value = _mock_response(
        status_code=503, headers={"cf-mitigated": "challenge"}
    )
    mock_render.return_value = _ok_rendered()

    OnyxWebCrawler()._fetch_url("https://example.com/")

    mock_render.assert_called_once()


@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.fetch_rendered_html")
@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.ssrf_safe_get")
def test_4xx_with_server_cloudflare_triggers_playwright_fallback(
    mock_get: MagicMock, mock_render: MagicMock
) -> None:
    mock_get.return_value = _mock_response(
        status_code=503, headers={"Server": "cloudflare"}
    )
    mock_render.return_value = _ok_rendered()

    OnyxWebCrawler()._fetch_url("https://example.com/")

    mock_render.assert_called_once()


# ---------------------------------------------------------------------------
# Conservatism: don't fire Playwright when there's no reason to.
# ---------------------------------------------------------------------------


@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.fetch_rendered_html")
@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.ssrf_safe_get")
def test_2xx_skips_playwright_fallback(
    mock_get: MagicMock, mock_render: MagicMock
) -> None:
    mock_get.return_value = _mock_response(
        status_code=200, content=SUCCESS_HTML.encode()
    )

    result = OnyxWebCrawler()._fetch_url("https://example.com/")

    mock_render.assert_not_called()
    assert result.scrape_successful


@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.fetch_rendered_html")
@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.ssrf_safe_get")
def test_404_without_cloudflare_signals_skips_playwright_fallback(
    mock_get: MagicMock, mock_render: MagicMock
) -> None:
    mock_get.return_value = _mock_response(status_code=404)

    result = OnyxWebCrawler()._fetch_url("https://example.com/missing")

    mock_render.assert_not_called()
    assert not result.scrape_successful


@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.fetch_rendered_html")
@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.ssrf_safe_get")
def test_401_without_cloudflare_signals_skips_playwright_fallback(
    mock_get: MagicMock, mock_render: MagicMock
) -> None:
    mock_get.return_value = _mock_response(status_code=401)

    OnyxWebCrawler()._fetch_url("https://example.com/private")

    mock_render.assert_not_called()


@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.fetch_rendered_html")
@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.ssrf_safe_get")
def test_500_without_cloudflare_signals_skips_playwright_fallback(
    mock_get: MagicMock, mock_render: MagicMock
) -> None:
    mock_get.return_value = _mock_response(status_code=500)

    OnyxWebCrawler()._fetch_url("https://example.com/")

    mock_render.assert_not_called()


# ---------------------------------------------------------------------------
# Feature flag and fallback failure behavior.
# ---------------------------------------------------------------------------


@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.fetch_rendered_html")
@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.ssrf_safe_get")
def test_fallback_disabled_skips_playwright(
    mock_get: MagicMock, mock_render: MagicMock
) -> None:
    mock_get.return_value = _mock_response(status_code=403)

    crawler = OnyxWebCrawler(playwright_fallback_enabled=False)
    result = crawler._fetch_url("https://example.com/")

    mock_render.assert_not_called()
    assert not result.scrape_successful


@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.fetch_rendered_html")
@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.ssrf_safe_get")
def test_fallback_render_returns_none_yields_failure(
    mock_get: MagicMock, mock_render: MagicMock
) -> None:
    """If Playwright itself fails (e.g. Chromium not installed), we surface failure."""
    mock_get.return_value = _mock_response(status_code=403)
    mock_render.return_value = None

    result = OnyxWebCrawler()._fetch_url("https://example.com/")

    mock_render.assert_called_once()
    assert not result.scrape_successful


@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.fetch_rendered_html")
@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.ssrf_safe_get")
def test_fallback_returns_empty_page_yields_failure(
    mock_get: MagicMock, mock_render: MagicMock
) -> None:
    """A render that comes back empty (e.g. CF challenge never resolved) is a failure."""
    mock_get.return_value = _mock_response(status_code=403)
    mock_render.return_value = RenderedPage(
        html=EMPTY_HTML, final_url="https://example.com/", status=403
    )

    result = OnyxWebCrawler()._fetch_url("https://example.com/")

    mock_render.assert_called_once()
    assert not result.scrape_successful


@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.fetch_rendered_html")
@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.ssrf_safe_get")
def test_fallback_respects_max_html_size(
    mock_get: MagicMock, mock_render: MagicMock
) -> None:
    mock_get.return_value = _mock_response(status_code=403)
    huge_html = "<html><body>" + "x" * 5000 + "</body></html>"
    mock_render.return_value = RenderedPage(
        html=huge_html, final_url="https://example.com/", status=200
    )

    crawler = OnyxWebCrawler(max_html_size_bytes=100)
    result = crawler._fetch_url("https://example.com/")

    mock_render.assert_called_once()
    assert not result.scrape_successful


# ---------------------------------------------------------------------------
# Cloudflare challenge body detection: when Playwright DOES render but the
# rendered HTML is still the CF challenge interstitial, we must NOT pass
# garbage like "Just a moment..." back to the LLM as if it were the page.
# ---------------------------------------------------------------------------


@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.fetch_rendered_html")
@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.ssrf_safe_get")
def test_rendered_cloudflare_challenge_body_yields_failure_with_reason(
    mock_get: MagicMock, mock_render: MagicMock
) -> None:
    """If Playwright rendered the CF challenge page itself, surface a clear
    Cloudflare-specific failure reason instead of silently returning the
    challenge HTML's text content."""
    mock_get.return_value = _mock_response(status_code=403)
    mock_render.return_value = RenderedPage(
        html=CF_CHALLENGE_HTML, final_url="https://example.com/", status=403
    )

    result = OnyxWebCrawler()._fetch_url("https://example.com/")

    mock_render.assert_called_once()
    assert not result.scrape_successful
    assert result.failure_reason == FailureReason.CLOUDFLARE_CHALLENGE


@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.fetch_rendered_html")
@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.ssrf_safe_get")
def test_render_failure_with_cf_signals_yields_cloudflare_reason(
    mock_get: MagicMock, mock_render: MagicMock
) -> None:
    """When the original 403 had actual CF headers AND Playwright failed to
    render, the surfaced reason should call out Cloudflare specifically."""
    mock_get.return_value = _mock_response(
        status_code=403, headers={"cf-mitigated": "challenge"}
    )
    mock_render.return_value = None

    result = OnyxWebCrawler()._fetch_url("https://example.com/")

    assert not result.scrape_successful
    assert result.failure_reason == FailureReason.CLOUDFLARE_CHALLENGE


@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.fetch_rendered_html")
@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.ssrf_safe_get")
def test_bare_403_without_cf_signals_yields_generic_403_reason(
    mock_get: MagicMock, mock_render: MagicMock
) -> None:
    """A 403 with no Cloudflare evidence shouldn't be labelled as Cloudflare —
    it's far more likely to be an auth wall or restricted resource. Playwright
    is still tried as cheap insurance, but the reason is honest."""
    mock_get.return_value = _mock_response(status_code=403)
    mock_render.return_value = None

    result = OnyxWebCrawler()._fetch_url("https://example.com/")

    mock_render.assert_called_once()  # fallback still tried
    assert not result.scrape_successful
    assert result.failure_reason == FailureReason.HTTP_403_BLOCKED


# ---------------------------------------------------------------------------
# Failure-reason coverage on non-CF paths: every failure path should set
# `failure_reason` so the open_url tool can pass it to the LLM.
# ---------------------------------------------------------------------------


@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.ssrf_safe_get")
def test_404_failure_reason_includes_status(mock_get: MagicMock) -> None:
    mock_get.return_value = _mock_response(status_code=404)

    result = OnyxWebCrawler()._fetch_url("https://example.com/missing")

    assert not result.scrape_successful
    assert result.failure_reason == FailureReason.http_status(404)


@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.ssrf_safe_get")
def test_ssrf_failure_reason(mock_get: MagicMock) -> None:
    from onyx.utils.url import SSRFException

    mock_get.side_effect = SSRFException("internal IP")

    result = OnyxWebCrawler()._fetch_url("http://internal.local/")

    assert not result.scrape_successful
    assert result.failure_reason == FailureReason.SSRF_BLOCKED


@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.ssrf_safe_get")
def test_network_error_failure_reason(mock_get: MagicMock) -> None:
    mock_get.side_effect = RuntimeError("connection reset")

    result = OnyxWebCrawler()._fetch_url("https://example.com/")

    assert not result.scrape_successful
    assert result.failure_reason == FailureReason.NETWORK_ERROR


@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.ssrf_safe_get")
def test_403_with_cf_signals_and_fallback_disabled_yields_cloudflare_reason(
    mock_get: MagicMock,
) -> None:
    """A 403 with actual CF headers should still label as a CF challenge
    even without invoking Playwright — admins shouldn't have to enable
    the fallback to find out why their URL is failing."""
    mock_get.return_value = _mock_response(
        status_code=403, headers={"cf-ray": "9f4994882a46eb36-SJC"}
    )

    crawler = OnyxWebCrawler(playwright_fallback_enabled=False)
    result = crawler._fetch_url("https://example.com/")

    assert not result.scrape_successful
    assert result.failure_reason == FailureReason.CLOUDFLARE_CHALLENGE


@patch("onyx.tools.tool_implementations.open_url.onyx_web_crawler.ssrf_safe_get")
def test_bare_403_with_fallback_disabled_yields_generic_403_reason(
    mock_get: MagicMock,
) -> None:
    """No CF headers + fallback disabled: don't pretend it's Cloudflare."""
    mock_get.return_value = _mock_response(status_code=403)

    crawler = OnyxWebCrawler(playwright_fallback_enabled=False)
    result = crawler._fetch_url("https://example.com/")

    assert not result.scrape_successful
    assert result.failure_reason == FailureReason.HTTP_403_BLOCKED


# ---------------------------------------------------------------------------
# The fallback path routes through the helper module so existing tests that
# patch `ssrf_safe_get` directly continue to work; this test exists to lock
# in the import name we expose for monkey-patching.
# ---------------------------------------------------------------------------


def test_fetch_rendered_html_is_importable_from_crawler_module() -> None:
    assert hasattr(crawler_module, "fetch_rendered_html")
    assert hasattr(crawler_module, "RenderedPage")
    assert hasattr(crawler_module, "looks_like_cloudflare_challenge")
