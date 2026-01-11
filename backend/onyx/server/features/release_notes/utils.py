"""Utility functions for release notes parsing and caching."""

import re
from datetime import datetime
from datetime import timezone

import httpx
from sqlalchemy.orm import Session

from onyx import __version__
from onyx.configs.constants import OnyxRedisLocks
from onyx.db.release_notes import create_release_notifications_for_versions
from onyx.redis.redis_pool import get_shared_redis_client
from onyx.server.features.release_notes.constants import AUTO_REFRESH_THRESHOLD_SECONDS
from onyx.server.features.release_notes.constants import FETCH_TIMEOUT
from onyx.server.features.release_notes.constants import GITHUB_CHANGELOG_RAW_URL
from onyx.server.features.release_notes.constants import REDIS_CACHE_TTL
from onyx.server.features.release_notes.constants import REDIS_KEY_ETAG
from onyx.server.features.release_notes.constants import REDIS_KEY_FETCHED_AT
from onyx.server.features.release_notes.models import ReleaseNoteEntry
from onyx.utils.logger import setup_logger

logger = setup_logger()


# ============================================================================
# Version Utilities
# ============================================================================


def is_valid_version(version: str) -> bool:
    """Check if version matches vX.Y.Z or vX.Y.Z-suffix.N pattern exactly."""
    return bool(re.match(r"^v\d+\.\d+\.\d+(-[a-zA-Z]+\.\d+)?$", version))


def parse_version_tuple(version: str) -> tuple[int, int, int]:
    """Parse version string to tuple for semantic sorting."""
    clean = re.sub(r"^v", "", version)
    clean = re.sub(r"-.*$", "", clean)
    parts = clean.split(".")
    return (
        int(parts[0]) if len(parts) > 0 else 0,
        int(parts[1]) if len(parts) > 1 else 0,
        int(parts[2]) if len(parts) > 2 else 0,
    )


def is_version_gte(v1: str, v2: str) -> bool:
    """Check if v1 >= v2. Strips suffixes like -cloud.X or -beta.X."""
    return parse_version_tuple(v1) >= parse_version_tuple(v2)


# ============================================================================
# MDX Parsing
# ============================================================================


def parse_mdx_to_release_note_entries(mdx_content: str) -> list[ReleaseNoteEntry]:
    """Parse MDX content into ReleaseNoteEntry objects for versions >= __version__."""
    all_entries = []

    update_pattern = (
        r'<Update\s+label="([^"]+)"\s+description="([^"]+)"'
        r"(?:\s+tags=\{([^}]+)\})?[^>]*>"
        r".*?"
        r"</Update>"
    )

    for match in re.finditer(update_pattern, mdx_content, re.DOTALL):
        version = match.group(1)
        date = match.group(2)

        if is_valid_version(version):
            all_entries.append(
                ReleaseNoteEntry(
                    version=version,
                    date=date,
                    title=f"Onyx {version} is available!",
                )
            )

    if not all_entries:
        raise ValueError("Could not parse any release note entries from MDX.")

    # Filter to valid versions >= __version__
    if __version__ and is_valid_version(__version__):
        entries = [
            entry for entry in all_entries if is_version_gte(entry.version, __version__)
        ]
    else:
        # If not recognized version
        # likely `development` and we should show all entries
        entries = all_entries

    return entries


# ============================================================================
# Cache Helpers (ETag + timestamp only)
# ============================================================================


def get_cached_etag() -> str | None:
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


def get_last_fetch_time() -> datetime | None:
    """Get the last fetch timestamp from Redis."""
    redis_client = get_shared_redis_client()
    try:
        fetched_at_str = redis_client.get(REDIS_KEY_FETCHED_AT)
        if not fetched_at_str:
            return None

        decoded = (
            fetched_at_str.decode("utf-8")
            if isinstance(fetched_at_str, bytes)
            else str(fetched_at_str)
        )

        last_fetch = datetime.fromisoformat(decoded)

        # Defensively ensure timezone awareness
        # fromisoformat() returns naive datetime if input lacks timezone
        if last_fetch.tzinfo is None:
            # Assume UTC for naive datetimes
            last_fetch = last_fetch.replace(tzinfo=timezone.utc)
        else:
            # Convert to UTC if timezone-aware
            last_fetch = last_fetch.astimezone(timezone.utc)

        return last_fetch
    except Exception as e:
        logger.error(f"Failed to get last fetch time from Redis: {e}")
        return None


def save_fetch_metadata(etag: str | None) -> None:
    """Save ETag and fetch timestamp to Redis."""
    redis_client = get_shared_redis_client()
    now = datetime.now(timezone.utc)

    try:
        redis_client.set(REDIS_KEY_FETCHED_AT, now.isoformat(), ex=REDIS_CACHE_TTL)
        if etag:
            redis_client.set(REDIS_KEY_ETAG, etag, ex=REDIS_CACHE_TTL)
    except Exception as e:
        logger.error(f"Failed to save fetch metadata to Redis: {e}")


def is_cache_stale() -> bool:
    """Check if we should fetch from GitHub."""
    last_fetch = get_last_fetch_time()
    if last_fetch is None:
        return True
    age = datetime.now(timezone.utc) - last_fetch
    return age.total_seconds() > AUTO_REFRESH_THRESHOLD_SECONDS


# ============================================================================
# Main Function
# ============================================================================


def ensure_release_notes_fresh_and_notify(db_session: Session) -> None:
    """
    Check for new release notes and create notifications if needed.

    Called from /api/notifications endpoint. Uses ETag for efficient
    GitHub requests. Database handles notification deduplication.

    Since all users will trigger this via notification fetch,
    uses Redis lock to prevent concurrent GitHub requests when cache is stale.
    """
    if not is_cache_stale():
        return

    # Acquire lock to prevent concurrent fetches
    redis_client = get_shared_redis_client()
    lock = redis_client.lock(
        OnyxRedisLocks.RELEASE_NOTES_FETCH_LOCK,
        timeout=90,  # 90 second timeout for the lock
    )

    # Non-blocking acquire - if we can't get the lock, another request is handling it
    acquired = lock.acquire(blocking=False)
    if not acquired:
        logger.debug("Another request is already fetching release notes, skipping.")
        return

    try:
        logger.debug("Checking GitHub for release notes updates.")

        # Use ETag for conditional request
        headers: dict[str, str] = {}
        etag = get_cached_etag()
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
                # Content unchanged, just update timestamp
                logger.debug("Release notes unchanged (304).")
                save_fetch_metadata(etag)
                return

            response.raise_for_status()

            # Parse and create notifications
            entries = parse_mdx_to_release_note_entries(response.text)
            new_etag = response.headers.get("ETag")
            save_fetch_metadata(new_etag)

            # Create notifications, sorted semantically to create them in chronological order
            entries = sorted(entries, key=lambda x: parse_version_tuple(x.version))
            create_release_notifications_for_versions(db_session, entries)

        except Exception as e:
            logger.error(f"Failed to check release notes: {e}")
            # Update timestamp even on failure to prevent retry storms
            # We don't save etag on failure to allow retry with conditional request
            save_fetch_metadata(None)
    finally:
        # Always release the lock
        if lock.owned():
            lock.release()
