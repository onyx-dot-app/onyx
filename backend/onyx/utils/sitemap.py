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


def _extract_urls_from_sitemap(sitemap_url: str) -> Set[str]:
    """Extract URLs from a sitemap XML file"""
    urls: set[str] = set()
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
            # This is a sitemap index
            for sitemap in root.findall(f".//{ns}loc"):
                if sitemap.text:
                    sub_urls = _extract_urls_from_sitemap(sitemap.text)
                    urls.update(sub_urls)
        else:
            # This is a regular sitemap
            for url in root.findall(f".//{ns}loc"):
                if url.text:
                    urls.add(url.text)

    except Exception as e:
        logger.warning(f"Error processing sitemap {sitemap_url}: {e}")

    return urls


def list_pages_for_site(site: str) -> list[str]:
    """Get list of pages from a site's sitemaps"""
    site = site.rstrip("/")
    all_urls = set()

    # Try both common sitemap locations
    sitemap_paths = ["/sitemap.xml", "/sitemap_index.xml"]
    for path in sitemap_paths:
        sitemap_url = urljoin(site, path)
        all_urls.update(_extract_urls_from_sitemap(sitemap_url))

    # Check robots.txt for additional sitemaps
    sitemap_locations = _get_sitemap_locations_from_robots(site)
    for sitemap_url in sitemap_locations:
        all_urls.update(_extract_urls_from_sitemap(sitemap_url))

    return list(all_urls)
