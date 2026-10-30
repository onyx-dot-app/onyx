"""The shape a source's webhook payload is parsed into.

A source-specific parser turns a provider's POST body into `ParsedEvent`s.
Everything downstream — deduplication, storage, the drain — works on this
shape, so a new source adds a parser and nothing else.
"""

import hashlib
import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from onyx.db.enums import ConnectorEventType


class ParsedEvent(BaseModel):
    """One document change a source reported, ready to store."""

    # The source's own stable id for the document, which becomes Document.id.
    document_id: str
    event_type: ConnectorEventType = ConnectorEventType.UPSERT

    # The provider's delivery id when it sends one. Unique per pair, so a
    # redelivered webhook writes nothing. Falls back to a digest of the
    # document and the event time, which collapses true redeliveries while
    # keeping genuinely new changes distinct.
    event_key: str = ""

    # Source-specific extras the drain needs. Never the document body: that
    # goes to the file store, and `file_id` points at it.
    payload: dict[str, Any] | None = None
    file_id: str | None = None

    # When the source says the change happened. Orders two events on one
    # document; the row id breaks ties when a provider sends no timestamp.
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
        """The key the unique constraint dedupes on, scoped to one document.

        A provider's delivery id usually covers the whole POST, and a POST
        can report several documents, so the document is always part of the
        key. Without it a batch of changes would collapse to one row.

        With no delivery id the key is a digest of the change itself, so a
        redelivery collapses and a different change does not. Two changes
        that match on document, type, time and payload are indistinguishable
        and treated as one.
        """
        if self.event_key:
            # A JSON array, not a joined string: `("a:b", "c")` and
            # `("a", "b:c")` would share a delimiter-joined key and one of
            # the two changes would be dropped as a duplicate.
            return json.dumps([self.event_key, self.document_id])

        stamp = self.occurred_at.isoformat() if self.occurred_at else ""
        digest = hashlib.sha256(
            json.dumps(
                [self.document_id, self.event_type.value, stamp, self.payload],
                sort_keys=True,
            ).encode()
        ).hexdigest()
        return f"derived:{digest}"


class EventParseResult(BaseModel):
    """What one webhook body yielded.

    A provider may batch several changes into one POST, and may include
    entries Onyx ignores. Keeping the ignored count separate lets the route
    answer 200 for a body it understood but had nothing to do with, rather
    than looking like a parser that silently dropped work.
    """

    events: list[ParsedEvent] = Field(default_factory=list)
    ignored: int = 0
