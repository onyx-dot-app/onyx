from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, model_validator


def _is_aware(value: datetime) -> bool:
    # A tzinfo whose utcoffset() returns None still makes a naive datetime.
    return value.tzinfo is not None and value.utcoffset() is not None


class BackfillSpec(BaseModel):
    """A one-off run over a fixed window that leaves the pair's incremental
    cursor alone, optionally with a config other than the saved one."""

    window_start: datetime
    window_end: datetime
    connector_config_override: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_window(self) -> "BackfillSpec":
        if not (_is_aware(self.window_start) and _is_aware(self.window_end)):
            raise ValueError("Backfill window bounds must be timezone-aware.")
        if self.window_start >= self.window_end:
            raise ValueError("Backfill window start must be before its end.")
        return self


class PendingBackfill(BaseModel):
    """A backfill an applied edit requested, kept on the cc-pair until the
    indexing beat can create its attempt."""

    request_id: UUID
    # DB time of the request. A full re-index created after it covers it.
    requested_at: datetime
    backfill: BackfillSpec
