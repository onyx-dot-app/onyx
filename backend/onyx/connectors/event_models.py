"""What a source's parser turns a webhook body into."""

import hashlib
import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from onyx.db.enums import ConnectorEventType


class ParsedEvent(BaseModel):
    """One document change a source reported, ready to store."""

    document_id: str
    event_type: ConnectorEventType = ConnectorEventType.UPSERT

    # The provider's delivery id, if it sends one.
    event_key: str = ""

    # Never the document body; `file_id` points at that.
    payload: dict[str, Any] | None = None
    file_id: str | None = None

    occurred_at: datetime | None = None

    @field_validator("document_id")
    @classmethod
    def _document_id_is_present(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("document_id cannot be blank")
        return value

    @field_validator("file_id")
    @classmethod
    def _file_id_is_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("file_id cannot be blank")
        return value

    def resolved_event_key(self) -> str:
        """The fixed-length key the inbox dedupes on.

        A delivery id can cover a POST that reports several documents, so the
        document is part of the key. Without a delivery id, the change itself
        is the key.
        """
        if self.event_key:
            # A JSON array, since a delimiter-joined pair is ambiguous.
            digest = hashlib.sha256(
                json.dumps([self.event_key, self.document_id]).encode()
            ).hexdigest()
            return f"delivery:{digest}"

        stamp = self.occurred_at.isoformat() if self.occurred_at else ""
        digest = hashlib.sha256(
            json.dumps(
                [self.document_id, self.event_type.value, stamp, self.payload],
                sort_keys=True,
            ).encode()
        ).hexdigest()
        return f"derived:{digest}"


class EventParseResult(BaseModel):
    """What one webhook body yielded. `ignored` counts entries the parser
    understood and skipped on purpose."""

    events: list[ParsedEvent] = Field(default_factory=list)
    ignored: int = 0
