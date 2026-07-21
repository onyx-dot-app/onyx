from datetime import datetime, timedelta, timezone


def datetime_to_utc(dt: datetime) -> datetime:
    """Normalize to timezone-aware UTC. Naive values are treated as UTC."""
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_window_start(dt: datetime, period_seconds: int) -> datetime:
    """Fixed UTC window start; weekly → Monday 00:00, else epoch-aligned."""
    dt = datetime_to_utc(dt)
    if period_seconds <= 0:
        raise ValueError("period_seconds must be positive")

    if period_seconds == 604_800:
        midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        return midnight - timedelta(days=dt.weekday())

    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    seconds_since_epoch = int((dt - epoch).total_seconds())
    window_number = seconds_since_epoch // period_seconds
    return epoch + timedelta(seconds=window_number * period_seconds)
