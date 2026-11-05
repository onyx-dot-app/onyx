"""The per-source part of the drain: how a stored event becomes a document."""

from collections.abc import Mapping
from typing import Protocol

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
from onyx.db.models import ConnectorEventInbox


class EventHandler(Protocol):
    """Turns one stored event into the document it describes."""

    def __call__(
        self, event: ConnectorEventInbox, secrets: Mapping[str, str]
    ) -> Document | None:
        """Return the document, or None to index nothing. `secrets` is the
        pair's credential, for a provider that pushes a link to the body.
        Raising retries this row alone."""


_HANDLERS: dict[DocumentSource, EventHandler] = {}


def register_event_handler(source: DocumentSource, handler: EventHandler) -> None:
    """Claim the drain for one source. Refuses a clash rather than replacing
    the incumbent."""
    existing = _HANDLERS.get(source)
    if existing is not None and existing is not handler:
        raise ValueError(f"{source.value} already has an event handler.")
    _HANDLERS[source] = handler


def unregister_event_handler(source: DocumentSource) -> None:
    """Ignores an unknown source."""
    _HANDLERS.pop(source, None)


def get_event_handler(source: DocumentSource) -> EventHandler | None:
    return _HANDLERS.get(source)


def event_handler_sources() -> set[DocumentSource]:
    return set(_HANDLERS)
