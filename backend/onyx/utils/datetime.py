from datetime import datetime
from datetime import timezone


def datetime_to_utc(dt: datetime) -> datetime:
    """Normalize to timezone-aware UTC. Naive values are treated as UTC."""
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
