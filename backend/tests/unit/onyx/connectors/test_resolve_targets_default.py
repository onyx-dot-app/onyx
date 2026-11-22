"""A Resolver that does not override resolve_targets gets each target through
reindex, with the document id and link it would get from a failure."""

from collections.abc import Generator
from typing import Any

from onyx.connectors.interfaces import Resolver
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    HierarchyNode,
    ListingPayload,
    ResolveTarget,
)


class _RecordingResolver(Resolver):
    def __init__(self) -> None:
        self.calls: list[tuple[list[ConnectorFailure], bool]] = []

    def load_credentials(self, credentials: dict[str, Any]) -> None:  # noqa: ARG002
        return None

    def reindex(
        self,
        errors: list[ConnectorFailure],
        include_permissions: bool = False,
    ) -> Generator[Document | ConnectorFailure | HierarchyNode, None, None]:
        self.calls.append((errors, include_permissions))
        yield from ()


def test_default_resolve_targets_calls_reindex() -> None:
    resolver = _RecordingResolver()
    targets = [
        ResolveTarget(document_id="doc-1", document_link="https://example.com/1"),
        ResolveTarget(document_id="doc-2", listing_payload=ListingPayload()),
    ]

    assert list(resolver.resolve_targets(targets, include_permissions=True)) == []

    assert len(resolver.calls) == 1
    errors, include_permissions = resolver.calls[0]
    assert include_permissions
    assert [
        (e.failed_document.document_id, e.failed_document.document_link)
        for e in errors
        if e.failed_document is not None
    ] == [("doc-1", "https://example.com/1"), ("doc-2", None)]
