"""API endpoints and utilities for release notes."""

import json
import re
from datetime import datetime
from datetime import timezone

import httpx
from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from onyx import __version__
from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.db.release_notes import create_release_notifications_for_versions
from onyx.redis.redis_pool import get_shared_redis_client
from onyx.server.features.release_notes.constants import AUTO_REFRESH_THRESHOLD_SECONDS
from onyx.server.features.release_notes.constants import DOCS_IMAGE_BASE_URL
from onyx.server.features.release_notes.constants import FETCH_TIMEOUT
from onyx.server.features.release_notes.constants import GITHUB_CHANGELOG_RAW_URL
from onyx.server.features.release_notes.constants import REDIS_CACHE_TTL
from onyx.server.features.release_notes.constants import REDIS_KEY_ENTRIES
from onyx.server.features.release_notes.constants import REDIS_KEY_ETAG
from onyx.server.features.release_notes.constants import REDIS_KEY_FETCHED_AT
from onyx.server.features.release_notes.models import CalloutVariant
from onyx.server.features.release_notes.models import ContentSection
from onyx.server.features.release_notes.models import ContentType
from onyx.server.features.release_notes.models import ReleaseNoteEntry
from onyx.server.features.release_notes.models import ReleaseNotesCacheData
from onyx.server.features.release_notes.models import ReleaseNotesResponse
from onyx.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter(prefix="/release-notes")


# ============================================================================
# Version Utilities
# ============================================================================


def _is_valid_version(version: str) -> bool:
    """Check if version matches vX.Y.Z pattern (with optional suffix)."""
    return bool(re.match(r"^v\d+\.\d+\.\d+", version))


def _is_version_gte(v1: str, v2: str) -> bool:
    """
    Check if v1 is greater than or equal to v2.

    Parses versions as (major, minor, patch) tuples and compares.
    E.g., v2.7.0 >= v2.6.0, v2.6.0 >= v2.6.0, v2.6.34 >= v2.4.1987
    Strips -cloud.X and -beta.X suffixes for comparison.
    """

    def parse_version(v: str) -> tuple[int, int, int]:
        # Strip v prefix and any suffix like -cloud.X or -beta.X
        clean = re.sub(r"^v", "", v)
        clean = re.sub(r"-.*$", "", clean)
        parts = clean.split(".")
        return (
            int(parts[0]) if len(parts) > 0 else 0,
            int(parts[1]) if len(parts) > 1 else 0,
            int(parts[2]) if len(parts) > 2 else 0,
        )

    return parse_version(v1) >= parse_version(v2)


# ============================================================================
# MDX Parsing
# ============================================================================


def _parse_content_sections(content: str) -> list[ContentSection]:
    """
    Parse the inner content of an Update block into structured sections.

    Handles: headings, images, callouts, and text paragraphs.
    """
    sections: list[ContentSection] = []

    # Normalize newlines (handle Windows \r\n and old Mac \r)
    content = content.replace("\r\n", "\n").replace("\r", "\n")

    # Remove the version header (## v2.7.0) - it's redundant with the metadata
    content = re.sub(r"^##\s+v[\d.]+\s*\n", "", content.strip())

    lines = content.split("\n")
    i = 0

    # Build regex pattern for callout tags
    callout_names = "|".join([variant.name.capitalize() for variant in CalloutVariant])

    def is_special_line(line: str) -> bool:
        """Check if line starts a special element (heading, image, callout)."""
        stripped = line.strip()
        if not stripped:
            return False
        if re.match(r"^#{1,4}\s+", stripped):
            return True
        if re.search(r'<img[^>]+src="[^"]+"', stripped):
            return True
        if re.match(rf"<({callout_names})>", stripped, re.IGNORECASE):
            return True
        return False

    while i < len(lines):
        line = lines[i].strip()

        # Skip leading empty lines
        if not line:
            i += 1
            continue

        # Heading (#, ##, ###, or ####)
        heading_match = re.match(r"^(#{1,4})\s+(.+)$", line)
        if heading_match:
            sections.append(
                ContentSection(
                    type=ContentType.HEADING,
                    content=heading_match.group(2).strip(),
                    level=len(heading_match.group(1)),
                )
            )
            i += 1
            continue

        # Image: <img ... src="..." alt="..."/>
        img_match = re.search(r'<img[^>]+src="([^"]+)"[^>]*alt="([^"]*)"', line)
        if img_match:
            img_src = img_match.group(1)
            # Prepend base URL for relative paths
            if img_src.startswith("/"):
                img_src = f"{DOCS_IMAGE_BASE_URL}{img_src}"
            sections.append(
                ContentSection(
                    type=ContentType.IMAGE,
                    content=img_match.group(2) or "",
                    src=img_src,
                )
            )
            i += 1
            continue

        # Callout: <Warning>, <Info>, <Note>, <Tip>
        callout_match = re.match(rf"<({callout_names})>", line, re.IGNORECASE)
        if callout_match:
            matched_name = callout_match.group(1).upper()
            variant = CalloutVariant[matched_name]
            # Build closing tag to look for (case-insensitive)
            closing_tag = f"</{matched_name.lower()}>"
            callout_content = []
            i += 1
            while i < len(lines):
                stripped = lines[i].strip().lower()

                if stripped == closing_tag:
                    i += 1
                    break
                callout_content.append(lines[i].strip())
                i += 1
            sections.append(
                ContentSection(
                    type=ContentType.CALLOUT,
                    content="\n".join(callout_content),
                    variant=variant,
                )
            )
            continue

        # Text paragraph - collect lines until we hit a special element
        text_lines = []
        while i < len(lines):
            current = lines[i]
            if is_special_line(current):
                break
            text_lines.append(current.strip())
            i += 1

        if text_lines:
            text_content = "\n".join(text_lines).strip()
            if text_content:
                sections.append(
                    ContentSection(type=ContentType.TEXT, content=text_content)
                )

    logger.debug(f"_parse_content_sections returning {len(sections)} sections")
    return sections


def _parse_mdx_to_release_note_entries(mdx_content: str) -> list[ReleaseNoteEntry]:
    """
    Parse MDX content into a list of ReleaseNoteEntry objects.

    Each <Update> block becomes one entry with parsed content sections.
    Only includes entries with versions newer than __version__.
    If __version__ is invalid, returns only the latest entry.
    """
    all_entries = []

    # Pattern to find Update blocks with their content
    update_pattern = (
        r'<Update\s+label="([^"]+)"\s+description="([^"]+)"'
        r"(?:\s+tags=\{([^}]+)\})?[^>]*>"
        r"(.*?)"
        r"</Update>"
    )

    for match in re.finditer(update_pattern, mdx_content, re.DOTALL):
        version = match.group(1)
        date = match.group(2)
        tags_str = match.group(3)
        inner_content = match.group(4)
        logger.debug(
            f"Found Update block: version={version}, date={date}, "
            f"inner_content_len={len(inner_content)}"
        )

        tags: list[str] = []
        if tags_str:
            tags = re.findall(r'"([^"]+)"', tags_str)

        sections = _parse_content_sections(inner_content)

        if not sections:
            logger.warning(f"No sections parsed for {version}! ")

        all_entries.append(
            ReleaseNoteEntry(
                version=version,
                date=date,
                tags=tags,
                title=f"Onyx {version} is available!",
                sections=sections,
            )
        )

    if not all_entries:
        raise ValueError(
            "Could not parse any release note entries from MDX. Release notes may be malformed."
        )

    # Filter to entries >= __version__ (current version and newer)
    if __version__ and _is_valid_version(__version__):
        entries = [
            entry
            for entry in all_entries
            if _is_version_gte(entry.version, __version__)
        ]
        logger.debug(
            f"Filtered {len(all_entries)} entries to {len(entries)} "
            f"(>= {__version__})"
        )
    else:
        entries = all_entries[:1]
        logger.debug(
            f"No valid app version ({__version__}), returning latest entry only"
        )

    return entries


# ============================================================================
# Redis Cache
# ============================================================================


def _get_cached_etag() -> str | None:
    """Get the cached GitHub ETag from Redis."""
    redis_client = get_shared_redis_client()
    try:
        etag = redis_client.get(REDIS_KEY_ETAG)
        if etag:
            return etag.decode("utf-8") if isinstance(etag, bytes) else str(etag)
        return None
    except Exception as e:
        logger.error(f"Failed to get cached etag from Redis: {e}")
        return None


def _get_cached_release_notes() -> ReleaseNotesCacheData | None:
    """Get the cached release notes entries from Redis."""
    redis_client = get_shared_redis_client()

    try:
        entries_json = redis_client.get(REDIS_KEY_ENTRIES)
        fetched_at_str = redis_client.get(REDIS_KEY_FETCHED_AT)

        if not entries_json or not fetched_at_str:
            logger.debug("No cached release notes found")
            return None

        entries_str: str = (
            entries_json.decode("utf-8")
            if isinstance(entries_json, bytes)
            else str(entries_json)
        )
        fetched_at_decoded: str = (
            fetched_at_str.decode("utf-8")
            if isinstance(fetched_at_str, bytes)
            else str(fetched_at_str)
        )

        entries_data = json.loads(entries_str)
        entries = [ReleaseNoteEntry(**entry) for entry in entries_data]

        if not entries:
            logger.warning("No release notes entries in cache")
            return None

        logger.debug("Found cached release notes.")
        return ReleaseNotesCacheData(
            entries=entries,
            fetched_at=datetime.fromisoformat(fetched_at_decoded),
        )
    except Exception as e:
        logger.error(f"Failed to get cached release notes from Redis: {e}")
        return None


def _save_release_notes_to_cache(
    entries: list[ReleaseNoteEntry],
    etag: str | None,
) -> None:
    """Save release notes entries to Redis cache."""
    redis_client = get_shared_redis_client()
    now = datetime.now(timezone.utc)

    try:
        # Log section counts before saving
        for entry in entries:
            logger.debug(
                f"Saving entry {entry.version} with {len(entry.sections)} sections"
            )

        entries_json = json.dumps([entry.model_dump() for entry in entries])
        logger.debug(
            f"Caching {len(entries)} entries, JSON length: {len(entries_json)}"
        )
        redis_client.set(REDIS_KEY_ENTRIES, entries_json, ex=REDIS_CACHE_TTL)
        redis_client.set(REDIS_KEY_FETCHED_AT, now.isoformat(), ex=REDIS_CACHE_TTL)

        if etag:
            redis_client.set(REDIS_KEY_ETAG, etag, ex=REDIS_CACHE_TTL)

        logger.debug("Cached release notes in Redis.")
    except Exception as e:
        logger.error(f"Failed to cache release notes to Redis: {e}")


def _update_cache_timestamp() -> None:
    """Update only the fetched_at timestamp (for 304 Not Modified responses)."""
    redis_client = get_shared_redis_client()
    now = datetime.now(timezone.utc)

    try:
        redis_client.set(REDIS_KEY_FETCHED_AT, now.isoformat(), ex=REDIS_CACHE_TTL)
        logger.debug("Updated release notes fetched_at in Redis.")
    except Exception as e:
        logger.error(f"Failed to update fetched_at in Redis: {e}")


def _is_cache_stale(fetched_at: datetime) -> bool:
    """Check if cache age exceeds the refresh threshold."""
    age = datetime.now(timezone.utc) - fetched_at
    return age.total_seconds() > AUTO_REFRESH_THRESHOLD_SECONDS


# ============================================================================
# GitHub Fetch
# ============================================================================


def _fetch_and_cache_release_notes(force: bool = False) -> ReleaseNotesCacheData:
    """
    Fetch release notes from GitHub and update cache.

    Uses conditional requests with ETag when not forcing.
    Only entries newer than __version__ will be included.
    """
    headers: dict[str, str] = {}

    if not force:
        etag = _get_cached_etag()
        if etag:
            headers["If-None-Match"] = etag

    try:
        response = httpx.get(
            GITHUB_CHANGELOG_RAW_URL,
            headers=headers,
            timeout=FETCH_TIMEOUT,
            follow_redirects=True,
        )

        if response.status_code == 304:
            logger.debug("304 Not Modified response from GitHub for release notes.")
            _update_cache_timestamp()
            cached = _get_cached_release_notes()
            if cached:
                return ReleaseNotesCacheData(
                    entries=cached.entries,
                    fetched_at=cached.fetched_at,
                    content_updated=False,
                )
            # Cache is unexpectedly empty after 304, force a full re-fetch
            logger.warning(
                "Received 304 Not Modified but cache is empty. Forcing full re-fetch."
            )
            return _fetch_and_cache_release_notes(force=True)

        response.raise_for_status()
        raw_content = response.text
        new_etag = response.headers.get("ETag")

    except httpx.HTTPError as e:
        logger.error(f"Failed to fetch release notes from GitHub: {e}")
        raise

    entries = _parse_mdx_to_release_note_entries(raw_content)
    _save_release_notes_to_cache(entries, new_etag)

    return ReleaseNotesCacheData(
        entries=entries,
        fetched_at=datetime.now(timezone.utc),
        content_updated=True,
    )


# ============================================================================
# API Helpers
# ============================================================================


def ensure_release_notes_fresh_and_notify(
    db_session: Session,
) -> ReleaseNotesCacheData | None:
    """
    Ensure release notes are fresh in cache.

    If cache is empty or stale, fetches from GitHub and creates
    notifications for all users.

    Returns the cached release notes, or None if unavailable.
    """
    cached = _get_cached_release_notes()
    needs_refresh = cached is None or _is_cache_stale(cached.fetched_at)

    if needs_refresh:
        logger.debug("Release notes cache is stale or empty. Fetching from GitHub.")
        try:
            cached = _fetch_and_cache_release_notes(force=False)
            if True or (cached and cached.content_updated):
                create_release_notifications_for_versions(db_session, cached.entries)
        except Exception as e:
            logger.error(f"Failed to refresh release notes: {e}")
            return cached

    return cached


# ============================================================================
# API Endpoints
# ============================================================================


REDIS_KEY_LAST_FORCE_REFRESH = "release_notes:last_force_refresh"
FORCE_REFRESH_COOLDOWN_SECONDS = 300  # 5 minutes cooldown between force refreshes


def _can_force_refresh() -> bool:
    """Check if enough time has passed since last force refresh."""
    redis_client = get_shared_redis_client()
    try:
        last_refresh = redis_client.get(REDIS_KEY_LAST_FORCE_REFRESH)
        if not last_refresh:
            return True

        last_refresh_str = (
            last_refresh.decode("utf-8")
            if isinstance(last_refresh, bytes)
            else str(last_refresh)
        )
        last_refresh_time = datetime.fromisoformat(last_refresh_str)
        elapsed = (datetime.now(timezone.utc) - last_refresh_time).total_seconds()
        return elapsed >= FORCE_REFRESH_COOLDOWN_SECONDS
    except Exception as e:
        logger.error(f"Error checking force refresh cooldown: {e}")
        return True  # Allow refresh on error


def _record_force_refresh() -> None:
    """Record the current time as the last force refresh."""
    redis_client = get_shared_redis_client()
    try:
        redis_client.set(
            REDIS_KEY_LAST_FORCE_REFRESH,
            datetime.now(timezone.utc).isoformat(),
            ex=FORCE_REFRESH_COOLDOWN_SECONDS * 2,  # Expire after 2x cooldown
        )
    except Exception as e:
        logger.error(f"Error recording force refresh time: {e}")


@router.get("")
def get_release_notes(
    version: str | None = None,
    force_refresh: bool = False,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> ReleaseNotesResponse:
    """
    Get the release notes entries as JSON.

    Auto-refreshes if stale and notifies all users.
    Individual notifications are dismissed via POST /api/notifications/{id}/dismiss.

    Query params:
    - version: If provided, returns only the entry for that specific version
    - force_refresh: If true, bypass cache and fetch fresh from GitHub
                     (subject to cooldown of 60 seconds between refreshes)
    """
    if force_refresh and _can_force_refresh():
        logger.info("Force refresh requested, bypassing cache")
        _record_force_refresh()
        cached = _fetch_and_cache_release_notes(force=True)
    else:

        cached = ensure_release_notes_fresh_and_notify(db_session)

    if cached is None:
        raise HTTPException(
            status_code=503,
            detail="Issue retrieving release notes from GitHub. Please visit https://docs.onyx.app/changelog",
        )

    entries = cached.entries

    # Filter to specific version if requested
    if version:
        entries = [e for e in entries if e.version == version]

    return ReleaseNotesResponse(
        entries=entries,
        fetched_at=cached.fetched_at,
    )
