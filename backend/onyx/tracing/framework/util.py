import uuid
from datetime import datetime
from datetime import timezone


def time_iso() -> str:
    """Return the current time in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def gen_trace_id() -> str:
    """Generate a new trace ID."""
    return f"trace_{uuid.uuid4().hex}"


def gen_span_id() -> str:
    """Generate a new span ID."""
    return f"span_{uuid.uuid4().hex[:24]}"
