"""Unit tests for ``onyx.utils.sitemap`` lastmod-aware parsing."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.utils import sitemap


def _fake_get(
    response_map: dict[str, bytes], status_map: dict[str, int] | None = None
) -> Any:
    """Return a fake ``requests.get`` that serves different bodies by URL."""

    def _get(url: str, **_: Any) -> MagicMock:
        resp = MagicMock()
        resp.status_code = (status_map or {}).get(url, 200)
        resp.content = response_map.get(url, b"")
        resp.text = resp.content.decode("utf-8", errors="ignore")
        return resp

    return _get


URLSET_WITH_LASTMOD = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://example.com/a</loc>
    <lastmod>2026-01-15T10:00:00+00:00</lastmod>
  </url>
  <url>
    <loc>https://example.com/b</loc>
    <lastmod>2024-06-01</lastmod>
  </url>
</urlset>
"""

URLSET_MIXED_LASTMOD = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/has-lastmod</loc><lastmod>2026-02-02</lastmod></url>
  <url><loc>https://example.com/no-lastmod</loc></url>
</urlset>
"""

URLSET_MALFORMED_LASTMOD = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/bad</loc><lastmod>not-a-date</lastmod></url>
</urlset>
"""

SITEMAPINDEX = b"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/sub-a.xml</loc></sitemap>
  <sitemap><loc>https://example.com/sub-b.xml</loc></sitemap>
</sitemapindex>
"""

SUB_A = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/child-a</loc><lastmod>2026-03-01</lastmod></url>
</urlset>
"""

SUB_B = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/child-b</loc></url>
</urlset>
"""


def test_extracts_lastmod_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sitemap.requests,
        "get",
        _fake_get({"https://example.com/sitemap.xml": URLSET_WITH_LASTMOD}),
    )

    result = sitemap._extract_urls_from_sitemap("https://example.com/sitemap.xml")

    assert set(result.keys()) == {"https://example.com/a", "https://example.com/b"}
    assert isinstance(result["https://example.com/a"], datetime)
    assert result["https://example.com/a"].year == 2026
    assert result["https://example.com/a"].month == 1
    assert result["https://example.com/b"] is not None
    assert result["https://example.com/b"].year == 2024


def test_missing_lastmod_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sitemap.requests,
        "get",
        _fake_get({"https://example.com/sitemap.xml": URLSET_MIXED_LASTMOD}),
    )

    result = sitemap._extract_urls_from_sitemap("https://example.com/sitemap.xml")

    assert result["https://example.com/has-lastmod"] is not None
    assert result["https://example.com/no-lastmod"] is None


def test_malformed_lastmod_is_none_not_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sitemap.requests,
        "get",
        _fake_get({"https://example.com/sitemap.xml": URLSET_MALFORMED_LASTMOD}),
    )

    result = sitemap._extract_urls_from_sitemap("https://example.com/sitemap.xml")

    assert result == {"https://example.com/bad": None}


def test_sitemapindex_merges_children(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sitemap.requests,
        "get",
        _fake_get(
            {
                "https://example.com/sitemap.xml": SITEMAPINDEX,
                "https://example.com/sub-a.xml": SUB_A,
                "https://example.com/sub-b.xml": SUB_B,
            }
        ),
    )

    result = sitemap._extract_urls_from_sitemap("https://example.com/sitemap.xml")

    assert set(result.keys()) == {
        "https://example.com/child-a",
        "https://example.com/child-b",
    }
    assert result["https://example.com/child-a"] is not None
    assert result["https://example.com/child-b"] is None
