"""Converting Drive files from their listing payload gives the same
documents as today's checkpointed load, with no files.get calls."""

import time
from typing import Any

import pytest

from onyx.connectors.google_drive import doc_conversion
from onyx.connectors.google_drive.models import DriveListingPayload
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    ResolveTarget,
)
from tests.external_dependency_unit.connectors.google_drive.conftest import MockDrive
from tests.external_dependency_unit.connectors.google_drive.test_checkpointed_slim_listing import (  # noqa: E501
    list_with_resume,
    listing_mode,  # noqa: F401
)


def _summary(docs: list[Document]) -> dict[str, tuple[str, Any, int]]:
    return {
        doc.id: (
            doc.semantic_identifier,
            (doc.doc_metadata or {}).get("hierarchy", {}).get("source_path"),
            len(doc.sections),
        )
        for doc in docs
    }


def _load_documents(mock_drive: MockDrive) -> list[Document]:
    """Today's path: the checkpointed full load."""
    connector = mock_drive.build_connector()
    checkpoint = connector.build_dummy_checkpoint()
    docs: list[Document] = []
    end = time.time()
    while checkpoint.has_more:
        generator = connector.load_from_checkpoint(0, end, checkpoint)
        while True:
            try:
                item = next(generator)
            except StopIteration as stop:
                checkpoint = stop.value
                break
            if isinstance(item, Document):
                docs.append(item)
    return docs


def _files_get_calls(mock_drive: MockDrive) -> int:
    ops = mock_drive.stats()["ops"]
    return int(ops.get("drive.files.get", {}).get("count", 0))


@pytest.mark.usefixtures("listing_mode")
def test_payload_conversion_matches_reindex(mock_drive: MockDrive) -> None:
    connector = mock_drive.build_connector()
    listing = list_with_resume(connector)
    assert listing.stubs

    targets: list[ResolveTarget] = []
    for stub in listing.stubs:
        assert stub.listing_payload is not None
        # The stub batch store keeps the payload as JSON.
        payload = DriveListingPayload.model_validate(
            stub.listing_payload.model_dump(mode="json")
        )
        targets.append(ResolveTarget(document_id=stub.id, listing_payload=payload))

    doc_conversion._folder_cache.clear()
    mock_drive.reset_stats()
    from_payload = list(connector.resolve_targets(targets))
    assert _files_get_calls(mock_drive) == 0

    doc_conversion._folder_cache.clear()
    today = _load_documents(mock_drive)

    assert today
    assert any(path for _, path, _ in _summary(today).values())
    assert not [r for r in from_payload if isinstance(r, ConnectorFailure)]
    assert _summary([d for d in from_payload if isinstance(d, Document)]) == _summary(
        today
    )
