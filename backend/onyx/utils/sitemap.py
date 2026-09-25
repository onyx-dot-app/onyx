import re
import xml.etree.ElementTree as ET
from typing import Set
from urllib.parse import urljoin

from onyx.utils.logger import setup_logger
from onyx.utils.url import ssrf_safe_get

logger = setup_logger()

MAX_SITEMAP_INDEX_DEPTH = 3
MAX_SITEMAPS_FETCHED = 50


def _get_sitemap_locations_from_robots(
    base_url: str, allow_private_network: bool = False, allow_loopback: bool = False
) -> Set[str]:
    """Extract sitemap URLs from robots.txt"""
    sitemap_urls: set[str] = set()
    try:
        robots_url = urljoin(base_url, "/robots.txt")
        resp = ssrf_safe_get(
            robots_url,
            timeout=10,
            allow_private_network=allow_private_network,
            block_loopback_and_link_local=not allow_loopback,
            block_link_local_only=True,
        )
        if resp.status_code == 200:
            for line in resp.text.splitlines():
                if line.lower().startswith("sitemap:"):
                    sitemap_url = line.split(":", 1)[1].strip()
                    sitemap_urls.add(sitemap_url)
    except Exception as e:
        logger.warning("Error fetching robots.txt: %s", e)
    return sitemap_urls


def _extract_urls_from_sitemap(
    sitemap_url: str,
    visited: set[str],
    allow_private_network: bool = False,
    depth: int = 0,
    allow_loopback: bool = False,
) -> Set[str]:
    """Extract URLs from a sitemap XML file."""
    urls: set[str] = set()
    if depth > MAX_SITEMAP_INDEX_DEPTH or len(visited) >= MAX_SITEMAPS_FETCHED:
        return urls
    if sitemap_url in visited:
        return urls
    visited.add(sitemap_url)

    try:
        resp = ssrf_safe_get(
            sitemap_url,
            timeout=10,
            allow_private_network=allow_private_network,
            block_loopback_and_link_local=not allow_loopback,
            block_link_local_only=True,
        )
        if resp.status_code != 200:
            return urls

        # TODO(security): switch to defusedxml.ElementTree. Modern xml.etree
        # disables DTD/external-entity processing by default, but element-
        # expansion (billion-laughs) DoS is still possible on attacker-
        # controlled sitemap content.
        root = ET.fromstring(resp.content)  # noqa: S314

        # Handle both regular sitemaps and sitemap indexes
        # Remove namespace for easier parsing
        namespace = re.match(r"\{.*\}", root.tag)
        ns = namespace.group(0) if namespace else ""

        if root.tag == f"{ns}sitemapindex":
            # This is a sitemap index
            for sitemap in root.findall(f".//{ns}loc"):
                if sitemap.text:
                    sub_urls = _extract_urls_from_sitemap(
                        sitemap.text,
                        visited,
                        allow_private_network,
                        depth + 1,
                        allow_loopback,
                    )
                    urls.update(sub_urls)
        else:
            # This is a regular sitemap
            for url in root.findall(f".//{ns}loc"):
                if url.text:
                    urls.add(url.text)

    except Exception as e:
        logger.warning("Error processing sitemap %s: %s", sitemap_url, e)

    return urls


def list_pages_for_site(
    site: str, allow_private_network: bool = False, allow_loopback: bool = False
) -> list[str]:
    """Get list of pages from a site's sitemaps"""
    site = site.rstrip("/")
    all_urls = set()
    visited: set[str] = set()

    # Try both common sitemap locations
    sitemap_paths = ["/sitemap.xml", "/sitemap_index.xml"]
    for path in sitemap_paths:
        sitemap_url = urljoin(site, path)
        all_urls.update(
            _extract_urls_from_sitemap(
                sitemap_url,
                visited,
                allow_private_network,
                allow_loopback=allow_loopback,
            )
        )

    # Check robots.txt for additional sitemaps
    sitemap_locations = _get_sitemap_locations_from_robots(
        site, allow_private_network, allow_loopback
    )
    for sitemap_url in sitemap_locations:
        all_urls.update(
            _extract_urls_from_sitemap(
                sitemap_url,
                visited,
                allow_private_network,
                allow_loopback=allow_loopback,
            )
        )

    return list(all_urls)
