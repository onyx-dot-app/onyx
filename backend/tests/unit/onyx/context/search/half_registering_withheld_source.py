"""A withheld source that registers and then fails, for the loader test."""

from collections.abc import Mapping, Sequence

from onyx.configs.constants import DocumentSource
from onyx.connectors.event_inbox.handlers import register_event_handler
from onyx.connectors.models import Document
from onyx.context.search.enrichment.registry import register_enrichment_source
from onyx.context.search.models import InferenceChunk
from onyx.db.models import ConnectorEventInbox

SOURCE = DocumentSource.MOCK_CONNECTOR


def _to_document(
    event: ConnectorEventInbox,  # noqa: ARG001
    secrets: Mapping[str, str],  # noqa: ARG001
) -> Document | None:
    return None


def _allowed(
    user_email: str,  # noqa: ARG001
    chunks: Sequence[InferenceChunk],  # noqa: ARG001
    secrets: Mapping[str, str],  # noqa: ARG001
) -> list[InferenceChunk]:
    return []


register_event_handler(SOURCE, _to_document)
register_enrichment_source(SOURCE, _allowed)

raise RuntimeError("this withheld source fails after registering")
