"""Utility functions for fetching and syncing custom broadcast notifications."""

from datetime import datetime
from datetime import timezone

import httpx
from sqlalchemy.orm import Session

from onyx.cache.factory import get_shared_cache_backend
from onyx.configs.constants import NotificationType
from onyx.db.custom_notifications import create_broadcast_notifications
from onyx.server.features.custom_notifications.constants import (
    AUTO_REFRESH_THRESHOLD_SECONDS,
)
from onyx.server.features.custom_notifications.constants import (
    CUSTOM_NOTIFICATIONS_RAW_URL,
)
from onyx.server.features.custom_notifications.constants import FETCH_TIMEOUT
from onyx.server.features.custom_notifications.constants import REDIS_CACHE_TTL
from onyx.server.features.custom_notifications.constants import REDIS_KEY_ETAG
from onyx.server.features.custom_notifications.constants import REDIS_KEY_FETCHED_AT
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _get_cached_etag() -> str | None:
    cache = get_shared_cache_backend()
    try:
        etag = cache.get(REDIS_KEY_ETAG)
        if etag:
            return etag.decode("utf-8")
        return None
    except Exception as e:
        logger.error(f"Failed to get cached etag for custom notifications: {e}")
        return None


def _get_last_fetch_time() -> datetime | None:
    cache = get_shared_cache_backend()
    try:
        raw = cache.get(REDIS_KEY_FETCHED_AT)
        if not raw:
            return None
        last_fetch = datetime.fromisoformat(raw.decode("utf-8"))
        if last_fetch.tzinfo is None:
            last_fetch = last_fetch.replace(tzinfo=timezone.utc)
        else:
            last_fetch = last_fetch.astimezone(timezone.utc)
        return last_fetch
    except Exception as e:
        logger.error(f"Failed to get last fetch time for custom notifications: {e}")
        return None


def _save_fetch_metadata(etag: str | None) -> None:
    cache = get_shared_cache_backend()
    now = datetime.now(timezone.utc)
    try:
        cache.set(REDIS_KEY_FETCHED_AT, now.isoformat(), ex=REDIS_CACHE_TTL)
        if etag:
            cache.set(REDIS_KEY_ETAG, etag, ex=REDIS_CACHE_TTL)
    except Exception as e:
        logger.error(f"Failed to save fetch metadata for custom notifications: {e}")


def _is_cache_stale() -> bool:
    last_fetch = _get_last_fetch_time()
    if last_fetch is None:
        return True
    age = datetime.now(timezone.utc) - last_fetch
    return age.total_seconds() > AUTO_REFRESH_THRESHOLD_SECONDS


def ensure_custom_notifications_fresh(db_session: Session) -> None:
    """
    Fetch custom broadcast notifications from the GitHub-hosted JSON feed
    and create notifications for all active users.

    Uses ETag caching and Redis locking (same pattern as release notes).
    """
    if not _is_cache_stale():
        return

    cache = get_shared_cache_backend()
    lock = cache.lock(
        "custom_notifications:fetch_lock",
        timeout=90,
    )

    acquired = lock.acquire(blocking=False)
    if not acquired:
        logger.debug(
            "Another request is already fetching custom notifications, skipping."
        )
        return

    try:
        logger.debug("Checking GitHub for custom broadcast notifications.")

        headers: dict[str, str] = {}
        etag = _get_cached_etag()
        if etag:
            headers["If-None-Match"] = etag

        try:
            response = httpx.get(
                CUSTOM_NOTIFICATIONS_RAW_URL,
                headers=headers,
                timeout=FETCH_TIMEOUT,
                follow_redirects=True,
            )

            if response.status_code == 304:
                logger.debug("Custom notifications unchanged (304).")
                _save_fetch_metadata(etag)
                return

            response.raise_for_status()

            notifications_data: list[dict] = response.json()
            new_etag = response.headers.get("ETag")
            _save_fetch_metadata(new_etag)

            for entry in notifications_data:
                entry_id = entry.get("id")
                title = entry.get("title", "")
                description = entry.get("description")
                link = entry.get("link")

                if not entry_id or not title:
                    logger.warning(
                        f"Skipping custom notification with missing id or title: {entry}"
                    )
                    continue

                additional_data: dict[str, str] = {"broadcast_id": entry_id}
                if link:
                    additional_data["link"] = link

                created = create_broadcast_notifications(
                    notif_type=NotificationType.CUSTOM_BROADCAST,
                    db_session=db_session,
                    title=title,
                    description=description,
                    additional_data=additional_data,
                )
                if created > 0:
                    logger.info(
                        f"Created {created} custom broadcast notifications "
                        f"(id={entry_id})"
                    )

        except Exception as e:
            logger.error(f"Failed to fetch custom notifications: {e}")
            _save_fetch_metadata(None)
    finally:
        if lock.owned():
            lock.release()
