"""Per-source conversion from a stored event to a document.

The drain is one connector for every event-based source, so the part that
differs — what a row's payload and stored body mean — lives here. A source
registers a handler; the drain looks it up by `DocumentSource`.
"""

from typing import Protocol

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
from onyx.db.models import ConnectorEventInbox


class EventHandler(Protocol):
    """Turns one stored event into the document it describes."""

    def __call__(self, event: ConnectorEventInbox) -> Document | None:
        """Return the document, or None to drop the event without failing it.

        Raising marks the one row failed and leaves the rest of the batch
        alone, so one bad payload cannot stall a pair.
        """


_HANDLERS: dict[DocumentSource, EventHandler] = {}


def register_event_handler(source: DocumentSource, handler: EventHandler) -> None:
    """Claim the drain for one source. Last registration wins."""
    _HANDLERS[source] = handler


def unregister_event_handler(source: DocumentSource) -> None:
    """Give up the drain for one source. Unknown sources are ignored."""
    _HANDLERS.pop(source, None)


def get_event_handler(source: DocumentSource) -> EventHandler | None:
    return _HANDLERS.get(source)
