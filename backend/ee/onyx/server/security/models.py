from datetime import datetime

from pydantic import BaseModel

from onyx.utils.audit import AuditEventCategory


class AuditClassStatus(BaseModel):
    # An OCSF class of the audit stream, or ``credential_access``.
    event_class: str
    events_last_24h: int
    last_event_at: datetime | None


class AuditStreamStatus(BaseModel):
    """What Onyx wrote to the audit stream. Onyx cannot see the log shipper or
    the SIEM, so this does not show that events arrived there."""

    # The license tier includes the audit stream.
    enabled: bool
    # The process log format. The docs recommend ``json``.
    log_format: str
    categories: list[AuditEventCategory]
    include_query_text: bool
    classes: list[AuditClassStatus]
