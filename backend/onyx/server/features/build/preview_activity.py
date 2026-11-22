"""App preview traffic as sandbox activity.

The webapp proxy records the time of the last preview request per session in
the cache. The idle reaper reads it before it puts a sandbox to sleep, so the
proxy's GET handler does no database write.
"""

from collections.abc import Iterable
from datetime import datetime, timezone
from uuid import UUID

from onyx.cache.factory import get_cache_backend
from onyx.server.features.build.configs import SANDBOX_IDLE_TIMEOUT_SECONDS


def _preview_activity_key(session_id: UUID) -> str:
    return f"craft:webapp:activity:{session_id}"


def mark_preview_activity(session_id: UUID) -> None:
    get_cache_backend().set(
        _preview_activity_key(session_id),
        str(datetime.now(timezone.utc).timestamp()),
        ex=SANDBOX_IDLE_TIMEOUT_SECONDS,
    )


def latest_preview_activity(session_ids: Iterable[UUID]) -> datetime | None:
    cache = get_cache_backend()
    latest: datetime | None = None
    for session_id in session_ids:
        raw = cache.get(_preview_activity_key(session_id))
        if raw is None:
            continue
        seen_at = datetime.fromtimestamp(float(raw.decode()), tz=timezone.utc)
        if latest is None or seen_at > latest:
            latest = seen_at
    return latest
