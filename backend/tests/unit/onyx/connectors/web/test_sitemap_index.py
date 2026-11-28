"""A sitemap connector pointed at a sitemap index must index the pages its
child sitemaps list, not the child sitemap files themselves."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from onyx.connectors.web import connector as web_connector
from onyx.connectors.web.connector import extract_urls_from_sitemap
from onyx.server.security.models import SSRFProtectionLevel
from onyx.utils import sitemap

_RESPONSES = {
    "https://example.com/sitemap_index.xml": (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        b"<sitemap><loc>https://example.com/post-sitemap.xml</loc></sitemap>"
        b"<sitemap><loc>https://example.com/page-sitemap.xml</loc></sitemap>"
        b"</sitemapindex>"
    ),
    "https://example.com/post-sitemap.xml": (
        b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        b"<url><loc>https://example.com/blog/first-post</loc></url>"
        b"</urlset>"
    ),
    "https://example.com/page-sitemap.xml": (
        b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        b"<url><loc>https://example.com/about</loc></url>"
        b"<url><loc>https://example.com/contact</loc></url>"
        b"</urlset>"
    ),
}


def _respond(url: str, **_: object) -> MagicMock:
    content = _RESPONSES.get(url)
    response = MagicMock(status_code=200 if content else 404, text="")
    response.content = content or b""
    return response


def test_sitemap_index_yields_pages_from_child_sitemaps() -> None:
    with (
        patch.object(web_connector, "protected_url_check"),
        patch.object(
            web_connector,
            "get_security_settings",
            return_value=SimpleNamespace(
                ssrf_protection_level=SSRFProtectionLevel.VALIDATE_ALL
            ),
        ),
        patch.object(web_connector, "ssrf_safe_get", side_effect=_respond),
        patch.object(sitemap, "ssrf_safe_get", side_effect=_respond),
    ):
        urls = extract_urls_from_sitemap("https://example.com/sitemap_index.xml")

    assert sorted(urls) == [
        "https://example.com/about",
        "https://example.com/blog/first-post",
        "https://example.com/contact",
    ]
