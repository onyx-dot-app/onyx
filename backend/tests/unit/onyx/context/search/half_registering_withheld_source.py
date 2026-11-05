"""A withheld source that registers and then fails, for the loader test."""

from collections.abc import Mapping, Sequence

from onyx.configs.constants import DocumentSource
from onyx.connectors.event_inbox.registration import register_event_source
from onyx.connectors.models import Document
from onyx.context.search.models import InferenceChunk
from onyx.db.models import ConnectorEventInbox
from tests.utils.event_sources import stub_webhook

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


register_event_source(
    webhook=stub_webhook(SOURCE, "half-registered-withheld"),
    handler=_to_document,
    permission_filter=_allowed,
)

raise RuntimeError("this withheld source fails after registering")
