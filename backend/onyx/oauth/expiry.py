"""Pure, clockless helpers for OAuth token expiry. A leaf module (imports nothing
from providers/orchestrator) so callers can use it without an import cycle.
"""

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any

# Refresh slightly early so no in-flight request reaches upstream with a just-
# expired token.
DEFAULT_REFRESH_SKEW_SECONDS = 120


def stamp_expires_at(credentials: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Return a *new* creds dict with an absolute ``expires_at`` derived from the
    response's relative ``expires_in``.

    A *missing* ``expires_in`` is left unstamped — "no ``expires_at``" means a
    non-expiring token (e.g. Slack/Linear). A *present-but-unparseable*
    ``expires_in`` is a corrupt value, not a non-expiring token, so it's stamped
    as already-expired (``now``): ``needs_refresh`` then treats it as stale and the
    refresh path heals it, rather than silently never refreshing a token that the
    provider said *does* expire.

    New dict, not a mutation — the input may be a ``SensitiveValue`` cache.
    """
    expires_in = credentials.get("expires_in")
    if expires_in is None:
        return dict(credentials)
    try:
        seconds = int(expires_in)
    except (TypeError, ValueError):
        # Corrupt expiry → stamp as already-expired so it refreshes, rather than
        # dropping it (which would read downstream as a non-expiring token).
        seconds = 0

    stamped = dict(credentials)
    stamped["expires_at"] = (now + timedelta(seconds=seconds)).isoformat()
    return stamped


def needs_refresh(
    credentials: dict[str, Any],
    now: datetime,
    skew_s: int = DEFAULT_REFRESH_SKEW_SECONDS,
) -> bool:
    """True iff the stored token is expired or within the skew window.

    A *missing* ``expires_at`` key → ``False``: a legitimately non-expiring token
    (e.g. Slack/Linear), never refreshed. A *present* ``expires_at`` that is empty,
    the wrong type, or otherwise unparseable is a corrupt value, not a non-expiring
    token (the only writer, ``stamp_expires_at``, always emits a valid ISO instant)
    → ``True``, so the refresh path heals it rather than silently keeping a token of
    unknown — likely expired — validity."""
    if "expires_at" not in credentials:
        return False
    try:
        expires_at = datetime.fromisoformat(credentials["expires_at"])
    except (TypeError, ValueError):
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return (expires_at - now).total_seconds() <= skew_s
