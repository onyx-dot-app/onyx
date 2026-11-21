from unittest.mock import patch

import pytest
import requests

from onyx.connectors.web import connector as web_connector
from onyx.connectors.web.config import WEB_CONNECTOR_VALID_SETTINGS
from onyx.connectors.web.connector import (
    WebConnector,
    extract_urls_from_sitemap,
)

SITEMAP_INDEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap>
    <loc>https://example.com/post-sitemap.xml</loc>
    <lastmod>2026-11-01T12:00:00+00:00</lastmod>
  </sitemap>
  <sitemap>
    <loc>https://example.com/page-sitemap.xml</loc>
    <lastmod>2026-11-01T12:00:00+00:00</lastmod>
  </sitemap>
</sitemapindex>
"""

POST_SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://example.com/posts/first-post</loc>
  </url>
  <url>
    <loc>https://example.com/posts/second-post</loc>
  </url>
</urlset>
"""

PAGE_SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://example.com/about</loc>
  </url>
</urlset>
"""

REGULAR_SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://example.com/home</loc>
  </url>
  <url>
    <loc>https://example.com/contact</loc>
  </url>
</urlset>
"""


def _mock_response(content: str, status_code: int = 200) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status_code
    resp._content = content.encode("utf-8")
    return resp


def test_extract_urls_from_regular_sitemap() -> None:
    sitemap_url = "https://example.com/sitemap.xml"
    with (
        patch.object(web_connector, "protected_url_check"),
        patch.object(
            web_connector,
            "ssrf_safe_get",
            return_value=_mock_response(REGULAR_SITEMAP_XML),
        ),
    ):
        urls = extract_urls_from_sitemap(sitemap_url)

    assert sorted(urls) == [
        "https://example.com/contact",
        "https://example.com/home",
    ]


def test_extract_urls_from_sitemap_index_extracts_child_pages() -> None:
    sitemap_index_url = "https://example.com/sitemap_index.xml"

    def mock_ssrf_safe_get(url: str, **_kwargs: object) -> requests.Response:
        if url == "https://example.com/sitemap_index.xml":
            return _mock_response(SITEMAP_INDEX_XML)
        elif url == "https://example.com/post-sitemap.xml":
            return _mock_response(POST_SITEMAP_XML)
        elif url == "https://example.com/page-sitemap.xml":
            return _mock_response(PAGE_SITEMAP_XML)
        return _mock_response("", status_code=404)

    with (
        patch.object(web_connector, "protected_url_check"),
        patch("onyx.utils.sitemap.ssrf_safe_get", side_effect=mock_ssrf_safe_get),
        patch(
            "onyx.connectors.web.connector.ssrf_safe_get",
            side_effect=mock_ssrf_safe_get,
        ),
    ):
        urls = extract_urls_from_sitemap(sitemap_index_url)

    # Must extract the pages from the child sitemaps, not the sitemap XML URLs themselves
    assert sorted(urls) == [
        "https://example.com/about",
        "https://example.com/posts/first-post",
        "https://example.com/posts/second-post",
    ]


def test_extract_urls_from_sitemap_index_with_relative_and_whitespace_urls() -> None:
    index_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap>
        <loc>
          //cdn.example.com/child-sitemap.xml
        </loc>
      </sitemap>
      <sitemap>
        <loc>   </loc>
      </sitemap>
    </sitemapindex>
    """
    child_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url>
        <loc>
          /nested-page
        </loc>
      </url>
      <url>
        <loc>   </loc>
      </url>
    </urlset>
    """

    def mock_ssrf_safe_get(url: str, **_kwargs: object) -> requests.Response:
        if url == "https://example.com/sitemap_index.xml":
            return _mock_response(index_xml)
        elif url == "https://cdn.example.com/child-sitemap.xml":
            return _mock_response(child_xml)
        return _mock_response("", status_code=404)

    with (
        patch.object(web_connector, "protected_url_check"),
        patch("onyx.utils.sitemap.ssrf_safe_get", side_effect=mock_ssrf_safe_get),
        patch(
            "onyx.connectors.web.connector.ssrf_safe_get",
            side_effect=mock_ssrf_safe_get,
        ),
    ):
        urls = extract_urls_from_sitemap("https://example.com/sitemap_index.xml")

    assert urls == ["https://cdn.example.com/nested-page"]


def test_web_connector_sitemap_mode_populates_to_visit_list_from_index() -> None:
    def mock_ssrf_safe_get(url: str, **_kwargs: object) -> requests.Response:
        if url == "https://example.com/sitemap_index.xml":
            return _mock_response(SITEMAP_INDEX_XML)
        elif url == "https://example.com/post-sitemap.xml":
            return _mock_response(POST_SITEMAP_XML)
        elif url == "https://example.com/page-sitemap.xml":
            return _mock_response(PAGE_SITEMAP_XML)
        return _mock_response("", status_code=404)

    with (
        patch.object(web_connector, "protected_url_check"),
        patch("onyx.utils.sitemap.ssrf_safe_get", side_effect=mock_ssrf_safe_get),
        patch(
            "onyx.connectors.web.connector.ssrf_safe_get",
            side_effect=mock_ssrf_safe_get,
        ),
    ):
        connector = WebConnector(
            base_url="https://example.com/sitemap_index.xml",
            web_connector_type=WEB_CONNECTOR_VALID_SETTINGS.SITEMAP.value,
        )

    assert sorted(connector.to_visit_list) == [
        "https://example.com/about",
        "https://example.com/posts/first-post",
        "https://example.com/posts/second-post",
    ]


def test_empty_sitemap_index_raises_value_error() -> None:
    empty_index_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    </sitemapindex>
    """
    with (
        patch.object(web_connector, "protected_url_check"),
        patch.object(
            web_connector,
            "ssrf_safe_get",
            return_value=_mock_response(empty_index_xml),
        ),
    ):
        with pytest.raises(RuntimeError, match="No URLs found in sitemap"):
            extract_urls_from_sitemap("https://example.com/empty_index.xml")
