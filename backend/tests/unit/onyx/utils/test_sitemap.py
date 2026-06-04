"""Unit tests for ``onyx.utils.sitemap`` lastmod-aware parsing."""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
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
    # Full W3C datetime: normalized to UTC.
    assert result["https://example.com/a"] == datetime(
        2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc
    )
    # Date-only: naive from dateutil, promoted to UTC midnight by our parser.
    assert result["https://example.com/b"] == datetime(
        2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc
    )


def test_missing_lastmod_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sitemap.requests,
        "get",
        _fake_get({"https://example.com/sitemap.xml": URLSET_MIXED_LASTMOD}),
    )

    result = sitemap._extract_urls_from_sitemap("https://example.com/sitemap.xml")

    assert result["https://example.com/has-lastmod"] == datetime(
        2026, 2, 2, 0, 0, 0, tzinfo=timezone.utc
    )
    assert result["https://example.com/no-lastmod"] is None


def test_non_utc_offset_normalized_to_utc() -> None:
    # +05:00 → same wall-clock shifted back 5 hours when normalized to UTC.
    assert sitemap.parse_sitemap_lastmod("2026-03-10T09:00:00+05:00") == datetime(
        2026, 3, 10, 4, 0, 0, tzinfo=timezone.utc
    )


def test_naive_input_treated_as_utc() -> None:
    # Naive datetime string → UTC (not local time).
    result = sitemap.parse_sitemap_lastmod("2026-03-10T12:34:56")
    assert result is not None
    assert result.tzinfo == timezone.utc
    assert result == datetime(2026, 3, 10, 12, 34, 56, tzinfo=timezone.utc)


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
    assert result["https://example.com/child-a"] == datetime(
        2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc
    )
    assert result["https://example.com/child-b"] is None
