"""URL normalization for OpenURL tool.

Each connector implements normalize_url() as a class method to normalize URLs to match
the canonical Document.id format used during ingestion. This ensures OpenURL can find
indexed documents.

Usage:
    normalized = normalize_url("https://docs.google.com/document/d/123/edit")
    # Returns: "https://docs.google.com/document/d/123"
"""

from urllib.parse import urlparse
from urllib.parse import urlunparse

from onyx.configs.constants import DocumentSource
from onyx.connectors.factory import identify_connector_class
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _default_url_normalizer(url: str) -> str | None:
    try:
        parsed = urlparse(url)
        if not parsed.netloc:
            return None

        # Strip query params and fragment, normalize trailing slash
        scheme = parsed.scheme or "https"
        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip("/")
        params = ""  # URL params (rarely used)
        query = ""  # Query string (removed)
        fragment = ""  # Fragment/hash (removed)

        normalized = urlunparse((scheme, netloc, path, params, query, fragment))
        return normalized or None
    except Exception as e:
        logger.debug(f"Default normalizer failed for URL {url}: {e}")
        return None


def normalize_url(url: str, source_type: DocumentSource | None = None) -> str | None:
    """Normalize a URL to match the canonical Document.id format.

    Dispatches to the connector's normalize_url() method or falls back to default normalizer.
    """
    if source_type:
        try:
            connector_class = identify_connector_class(source_type)
            result = connector_class.normalize_url(url)
        except Exception as e:
            logger.warning(
                f"Failed to normalize URL for {source_type}: {e}. Using default normalizer."
            )
            return _default_url_normalizer(url)

        if result:
            logger.debug(
                f"Normalized URL using {source_type} connector: {url} -> {result}"
            )
            return result

        # Connector either doesn't override normalize_url or returned None - fall back
        fallback = _default_url_normalizer(url)
        if fallback:
            logger.debug(
                f"Connector {source_type} returned no normalization for {url}, "
                f"using default: {fallback}"
            )
        return fallback

    # Try to detect source type from URL patterns
    detected = _detect_source_type(url)
    if detected:
        try:
            connector_class = identify_connector_class(detected)
            result = connector_class.normalize_url(url)
            if result:
                logger.debug(
                    f"Normalized URL using detected {detected} connector: {url} -> {result}"
                )
                return result
        except Exception as e:
            logger.debug(
                f"Detected {detected} but normalization failed: {e}. Using default normalizer."
            )
        # Fall through to default normalizer if connector returns None or raises exception
        return _default_url_normalizer(url)

    # No source detected - try default normalizer as last resort
    logger.debug(
        f"Could not detect source type for URL, trying default normalizer: {url}"
    )
    return _default_url_normalizer(url)


def _detect_source_type(url: str) -> DocumentSource | None:
    """Detect DocumentSource from URL patterns (simple heuristic)."""
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    path = parsed.path.lower()

    if "docs.google.com" in netloc or "drive.google.com" in netloc:
        return DocumentSource.GOOGLE_DRIVE
    if "notion.so" in netloc or "notion.site" in netloc:
        return DocumentSource.NOTION
    if "atlassian.net" in netloc:
        # Check path for Jira indicators (more specific than netloc)
        if "/jira/" in path or "/browse/" in path or "jira" in netloc:
            return DocumentSource.JIRA
        return DocumentSource.CONFLUENCE
    if "github.com" in netloc:
        return DocumentSource.GITHUB
    if "gitlab.com" in netloc:
        return DocumentSource.GITLAB
    if "sharepoint.com" in netloc:
        return DocumentSource.SHAREPOINT
    if "slack.com" in netloc:
        return DocumentSource.SLACK

    return None
