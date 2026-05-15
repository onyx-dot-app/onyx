import re
import xml.etree.ElementTree as ET
from datetime import datetime
from datetime import timezone
from typing import Set
from urllib.parse import urljoin

import requests
from dateutil import parser as dateutil_parser

from onyx.utils.logger import setup_logger

logger = setup_logger()


def parse_sitemap_lastmod(lastmod_text: str | None) -> datetime | None:
    """Parse a sitemap ``<lastmod>`` value into a timezone-aware UTC datetime.

    The sitemap spec permits both full W3C datetimes (``2026-01-15T10:00:00+00:00``)
    and date-only values (``2024-06-01``). Date-only strings yield a naive datetime
    from ``dateutil.parser``; to keep downstream ``.timestamp()`` calls consistent
    across host timezones we treat naive values as UTC midnight and normalize any
    aware value to UTC.

    Returns ``None`` on missing or unparseable input.
    """
    if not lastmod_text:
        return None
    try:
        parsed = dateutil_parser.parse(lastmod_text.strip())
    except (ValueError, TypeError, OverflowError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _get_sitemap_locations_from_robots(base_url: str) -> Set[str]:
    """Extract sitemap URLs from robots.txt"""
    sitemap_urls: set = set()
    try:
        robots_url = urljoin(base_url, "/robots.txt")
        resp = requests.get(robots_url, timeout=10)
        if resp.status_code == 200:
            for line in resp.text.splitlines():
                if line.lower().startswith("sitemap:"):
                    sitemap_url = line.split(":", 1)[1].strip()
                    sitemap_urls.add(sitemap_url)
    except Exception as e:
        logger.warning("Error fetching robots.txt: %s", e)
    return sitemap_urls


def _extract_urls_from_sitemap(sitemap_url: str) -> dict[str, datetime | None]:
    """Extract URLs and their ``<lastmod>`` from a sitemap XML file.

    Returns a mapping of URL to parsed lastmod datetime (or None if absent / unparseable).
    Sitemap-index entries are recursed; if the same URL appears in multiple sub-sitemaps
    the last one wins — sitemaps are expected to have unique URLs in practice.
    """
    urls: dict[str, datetime | None] = {}
    try:
        resp = requests.get(sitemap_url, timeout=10)
        if resp.status_code != 200:
            return urls

        root = ET.fromstring(resp.content)

        # Handle both regular sitemaps and sitemap indexes
        # Remove namespace for easier parsing
        namespace = re.match(r"\{.*\}", root.tag)
        ns = namespace.group(0) if namespace else ""

        if root.tag == f"{ns}sitemapindex":
            for sitemap in root.findall(f".//{ns}sitemap"):
                loc_el = sitemap.find(f"{ns}loc")
                if loc_el is not None and loc_el.text:
                    urls.update(_extract_urls_from_sitemap(loc_el.text))
        else:
            for url_el in root.findall(f".//{ns}url"):
                loc_el = url_el.find(f"{ns}loc")
                if loc_el is None or not loc_el.text:
                    continue
                lastmod_el = url_el.find(f"{ns}lastmod")
                urls[loc_el.text] = parse_sitemap_lastmod(
                    lastmod_el.text if lastmod_el is not None else None
                )

    except Exception as e:
        logger.warning("Error processing sitemap %s: %s", sitemap_url, e)

    return urls


def list_pages_for_site(site: str) -> dict[str, datetime | None]:
    """Get a mapping of URL → lastmod for pages discovered via a site's sitemaps."""
    site = site.rstrip("/")
    all_urls: dict[str, datetime | None] = {}

    # Try both common sitemap locations
    sitemap_paths = ["/sitemap.xml", "/sitemap_index.xml"]
    for path in sitemap_paths:
        sitemap_url = urljoin(site, path)
        all_urls.update(_extract_urls_from_sitemap(sitemap_url))

    # Check robots.txt for additional sitemaps
    sitemap_locations = _get_sitemap_locations_from_robots(site)
    for sitemap_url in sitemap_locations:
        all_urls.update(_extract_urls_from_sitemap(sitemap_url))

    return all_urls
