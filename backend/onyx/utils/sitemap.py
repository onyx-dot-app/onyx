import re
import xml.etree.ElementTree as ET
from typing import Set
from urllib.parse import urljoin

import requests

from onyx.utils.logger import setup_logger

logger = setup_logger()


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
        logger.warning(f"Error fetching robots.txt: {e}")
    return sitemap_urls


def _extract_urls_from_sitemap(sitemap_url: str) -> dict[str, str | None]:
    """Extract URLs and their lastmod values from a sitemap XML file

    Returns:
        Dictionary mapping URLs to their lastmod values (or None if not present)
    """
    urls_data: dict[str, str | None] = {}
    try:
        resp = requests.get(sitemap_url, timeout=10)
        if resp.status_code != 200:
            return urls_data

        root = ET.fromstring(resp.content)

        # Handle both regular sitemaps and sitemap indexes
        # Remove namespace for easier parsing
        namespace = re.match(r"\{.*\}", root.tag)
        ns = namespace.group(0) if namespace else ""

        if root.tag == f"{ns}sitemapindex":
            # This is a sitemap index
            for sitemap in root.findall(f".//{ns}loc"):
                if sitemap.text:
                    sub_url_data = _extract_urls_from_sitemap(sitemap.text)
                    urls_data.update(sub_url_data)
        else:
            # This is a regular sitemap
            for url_elem in root.findall(f".//{ns}url"):
                loc = url_elem.find(f"{ns}loc")
                lastmod = url_elem.find(f"{ns}lastmod")

                if loc is not None and loc.text:
                    lastmod_value = lastmod.text if lastmod is not None else None
                    urls_data[loc.text] = lastmod_value

    except Exception as e:
        logger.warning(f"Error processing sitemap {sitemap_url}: {e}")

    return urls_data


def list_pages_for_site(site: str) -> dict[str, str | None]:
    """Get list of pages from a site's sitemaps with their lastmod values

    Returns:
        Dictionary mapping URLs to their lastmod values (or None if not present)
    """
    site = site.rstrip("/")
    all_urls_data: dict[str, str | None] = {}

    # Try both common sitemap locations
    sitemap_paths = ["/sitemap.xml", "/sitemap_index.xml"]
    for path in sitemap_paths:
        sitemap_url = urljoin(site, path)
        all_urls_data.update(_extract_urls_from_sitemap(sitemap_url))

    # Check robots.txt for additional sitemaps
    sitemap_locations = _get_sitemap_locations_from_robots(site)
    for sitemap_url in sitemap_locations:
        all_urls_data.update(_extract_urls_from_sitemap(sitemap_url))

    return all_urls_data
