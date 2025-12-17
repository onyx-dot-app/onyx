"""URL normalization registry for OpenURL tool.

Each connector registers how to normalize its URLs to match the canonical Document.id
format used during ingestion. This ensures OpenURL can find indexed documents.

Usage:
    normalized = normalize_url("https://docs.google.com/document/d/123/edit")
    # Returns: "https://docs.google.com/document/d/123"
"""

import re
from collections.abc import Callable
from urllib.parse import parse_qs
from urllib.parse import urlparse
from urllib.parse import urlunparse

from onyx.configs.constants import DocumentSource
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Registry: DocumentSource -> normalization function
_NORMALIZERS: dict[DocumentSource, Callable[[str], str | None]] = {}


def register_normalizer(
    source: DocumentSource, normalizer: Callable[[str], str | None]
) -> None:
    """Register a URL normalizer for a connector.

    Connectors should call this during module import to register their normalization logic.

    Args:
        source: The DocumentSource this normalizer handles
        normalizer: Function that takes a URL and returns normalized Document.id, or None
    """
    _NORMALIZERS[source] = normalizer


def _default_url_normalizer(url: str) -> str | None:
    """Default normalizer for connectors that use URLs as Document.id.

    Most connectors store the URL directly as the document ID, possibly with
    query parameters and fragments stripped. This generic normalizer handles
    those cases automatically.

    Args:
        url: URL to normalize

    Returns:
        URL with query parameters and fragments removed, or None if invalid
    """
    try:
        parsed = urlparse(url)
        if not parsed.netloc:
            return None

        # Strip query params and fragment, normalize trailing slash
        normalized = urlunparse(
            (
                parsed.scheme or "https",
                parsed.netloc.lower(),
                parsed.path.rstrip("/"),
                "",
                "",  # Remove query
                "",  # Remove fragment
            )
        )
        return normalized or None
    except Exception as e:
        logger.debug(f"Default normalizer failed for URL {url}: {e}")
        return None


def normalize_url(url: str, source_type: DocumentSource | None = None) -> str | None:
    """Normalize a URL to match the canonical Document.id format.

    This is the main API for OpenURL tool. It dispatches to the appropriate
    connector's normalization function. If no connector-specific normalizer exists,
    falls back to a default normalizer that strips query parameters and fragments

    Prefer passing source_type when available (e.g., from search results) to skip
    detection and ensure correct normalization.

    Args:
        url: The URL to normalize
        source_type: Optional hint for which connector to use. If provided, skips
            detection and uses this connector's normalizer directly. If None, will try
            to detect from URL patterns. If no custom normalizer exists, uses default.

    Returns:
        Normalized URL string matching Document.id format, or None if normalization fails.
    """
    # If source_type provided, use its normalizer directly (skip detection)
    if source_type:
        if source_type in _NORMALIZERS:
            try:
                result = _NORMALIZERS[source_type](url)
                if result:
                    logger.debug(
                        f"Normalized URL using {source_type} normalizer: {url} -> {result}"
                    )
                return result
            except Exception as e:
                logger.warning(f"Normalizer for {source_type} failed on URL {url}: {e}")
                return None
        else:
            # No custom normalizer registered - use default (strip query/fragment)
            logger.debug(
                f"No custom normalizer for {source_type}, using default: {url}"
            )
            return _default_url_normalizer(url)

    # Try to detect source type from URL patterns
    detected = _detect_source_type(url)
    if detected:
        if detected in _NORMALIZERS:
            try:
                result = _NORMALIZERS[detected](url)
                if result:
                    logger.debug(
                        f"Normalized URL using detected {detected} normalizer: {url} -> {result}"
                    )
                return result
            except Exception as e:
                logger.warning(
                    f"Detected normalizer for {detected} failed on URL {url}: {e}"
                )
                return None
        else:
            # Detected source but no custom normalizer - use default
            logger.debug(
                f"Detected {detected} but no custom normalizer, using default: {url}"
            )
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


# ============================================================================
# Connector Normalizers
# Each connector registers its normalization logic here
# ============================================================================


def _register_google_drive_normalizer() -> None:
    """Register Google Drive URL normalizer using connector's own logic."""
    try:
        from onyx.connectors.google_drive.doc_conversion import (
            onyx_document_id_from_drive_file,
        )

        def normalize(url: str) -> str | None:
            parsed = urlparse(url)
            netloc = parsed.netloc.lower()

            if not (
                netloc.startswith("docs.google.com")
                or netloc.startswith("drive.google.com")
            ):
                return None

            # Handle ?id= query parameter case
            query_params = parse_qs(parsed.query)
            doc_id = query_params.get("id", [None])[0]
            if doc_id:
                scheme = parsed.scheme or "https"
                normalized = urlunparse(
                    (scheme, "drive.google.com", f"/file/d/{doc_id}", "", "", "")
                )
                return normalized.rstrip("/")

            # Extract file ID and use connector's function
            path_parts = parsed.path.split("/")
            file_id = None
            for i, part in enumerate(path_parts):
                if part == "d" and i + 1 < len(path_parts):
                    file_id = path_parts[i + 1]
                    break

            if not file_id:
                return None

            # Create minimal file object for connector function
            file_obj = {"webViewLink": url, "id": file_id}
            try:
                return onyx_document_id_from_drive_file(file_obj).rstrip("/")
            except Exception:
                # Fallback: strip /edit, /view, /preview
                parsed = parsed._replace(query="", fragment="")
                path_parts = parsed.path.split("/")
                if path_parts and path_parts[-1] in ["edit", "view", "preview"]:
                    path_parts.pop()
                    parsed = parsed._replace(path="/".join(path_parts))
                return urlunparse(parsed).rstrip("/")

        register_normalizer(DocumentSource.GOOGLE_DRIVE, normalize)
    except ImportError:
        logger.debug("Google Drive connector not available")


def _register_notion_normalizer() -> None:
    """Register Notion URL normalizer (extracts page ID)."""

    def normalize(url: str) -> str | None:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()

        if not ("notion.so" in netloc or "notion.site" in netloc):
            return None

        # Extract page ID from path (format: "Title-PageID")
        path_last = parsed.path.split("/")[-1]
        candidate = path_last.split("-")[-1] if "-" in path_last else path_last

        # Clean and format as UUID
        candidate = re.sub(r"[^0-9a-fA-F-]", "", candidate)
        cleaned = candidate.replace("-", "")

        if len(cleaned) == 32 and re.fullmatch(r"[0-9a-fA-F]{32}", cleaned):
            return (
                f"{cleaned[0:8]}-{cleaned[8:12]}-{cleaned[12:16]}-"
                f"{cleaned[16:20]}-{cleaned[20:]}"
            ).lower()

        # Try query params
        params = parse_qs(parsed.query)
        for key in ("p", "page_id"):
            if key in params and params[key]:
                candidate = params[key][0].replace("-", "")
                if len(candidate) == 32 and re.fullmatch(r"[0-9a-fA-F]{32}", candidate):
                    return (
                        f"{candidate[0:8]}-{candidate[8:12]}-{candidate[12:16]}-"
                        f"{candidate[16:20]}-{candidate[20:]}"
                    ).lower()

        return None

    register_normalizer(DocumentSource.NOTION, normalize)


def _register_slack_normalizer() -> None:
    """Register Slack URL normalizer (extracts channel_id__thread_ts format)."""

    def normalize(url: str) -> str | None:
        parsed = urlparse(url)
        if "slack.com" not in parsed.netloc.lower():
            return None

        # Slack document IDs are format: channel_id__thread_ts
        # Extract from URL pattern: .../archives/{channel_id}/p{timestamp}
        path_parts = parsed.path.split("/")
        try:
            archives_idx = path_parts.index("archives")
            if archives_idx + 1 < len(path_parts):
                channel_id = path_parts[archives_idx + 1]
                if archives_idx + 2 < len(path_parts):
                    thread_part = path_parts[archives_idx + 2]
                    if thread_part.startswith("p"):
                        # Convert p1234567890123456 to 1234567890.123456 format
                        timestamp_str = thread_part[1:]  # Remove 'p' prefix
                        if len(timestamp_str) == 16:
                            # Insert dot at position 10 to match canonical format
                            thread_ts = f"{timestamp_str[:10]}.{timestamp_str[10:]}"
                        else:
                            thread_ts = timestamp_str
                        return f"{channel_id}__{thread_ts}"
        except (ValueError, IndexError):
            pass

        return None

    register_normalizer(DocumentSource.SLACK, normalize)


# Auto-register all normalizers on module import
# TODO: Future improvement - auto-discover normalizers from connector metadata
_register_google_drive_normalizer()
_register_notion_normalizer()
_register_slack_normalizer()

# Add more connectors here as needed:
# _register_<connector>_normalizer()
