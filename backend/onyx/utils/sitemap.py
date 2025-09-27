import gzip
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

        content_to_parse = resp.content

        # Check if the URL ends with .gz. If so, attempt to decompress.
        # requests usually handles Content-Encoding: gzip automatically,
        # but if the server doesn't send that header for .gz files,
        # we need to decompress manually.
        if sitemap_url.endswith(".gz"):
            try:
                # Attempt to decompress the content
                decompressed_content = gzip.decompress(resp.content)
                content_to_parse = decompressed_content
                logger.info(f"Successfully decompressed gzipped sitemap: {sitemap_url}")
            except gzip.BadGzipFile:
                # If it's not a valid gzip file (e.g., already decompressed by requests,
                # or corrupted), log a warning and proceed with the original content.
                logger.warning(
                    f"Sitemap {sitemap_url} ends with .gz but is not a valid gzip file. Attempting to parse as-is."
                )
            except Exception as de_e:
                logger.warning(
                    f"Unexpected error during gzip decompression for {sitemap_url}: {de_e}. Proceeding with original content."
                )

        root = ET.fromstring(content_to_parse)

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
