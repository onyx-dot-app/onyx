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
    response's relative ``expires_in`` (unchanged if no ``expires_in`` — "no
    ``expires_at``" means "never expires").

    New dict, not a mutation — the input may be a ``SensitiveValue`` cache.
    """
    expires_in = credentials.get("expires_in")
    if expires_in is None:
        return dict(credentials)
    try:
        seconds = int(expires_in)
    except (TypeError, ValueError):
        return dict(credentials)

    stamped = dict(credentials)
    stamped["expires_at"] = (now + timedelta(seconds=seconds)).isoformat()
    return stamped


def needs_refresh(
    credentials: dict[str, Any],
    now: datetime,
    skew_s: int = DEFAULT_REFRESH_SKEW_SECONDS,
) -> bool:
    """True iff the stored token is expired or within the skew window. Missing or
    unparseable ``expires_at`` → ``False`` (treat as never-expiring)."""
    raw = credentials.get("expires_at")
    if not raw:
        return False
    try:
        expires_at = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return (expires_at - now).total_seconds() <= skew_s
