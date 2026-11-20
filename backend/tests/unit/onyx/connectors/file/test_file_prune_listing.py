"""The file connector's prune listing keeps the id of a file that failed to
process, and raises when the metadata that sets document ids is unreadable.
Indexing still skips such a file. A connector with no files lists nothing."""

from io import BytesIO
from unittest.mock import MagicMock

import pytest

from onyx.connectors.file import connector as file_connector
from onyx.connectors.file import metadata
from onyx.connectors.file.connector import LocalFileConnector
from onyx.connectors.file.metadata import ZipMetadataError, file_document_id
from onyx.connectors.models import Document, SlimDocument
from onyx.file_processing.extract_file_text import ExtractionResult

_FILES: dict[str, tuple[str, bytes]] = {
    "csv-file": ("table.csv", b"a,b\n1,2\n"),
    "txt-file": ("notes.txt", b"some notes"),
}


def _store() -> MagicMock:
    store = MagicMock()

    def _record(file_id: str) -> MagicMock:
        record = MagicMock()
        record.display_name = _FILES[file_id][0]
        record.file_type = None
        record.file_size = len(_FILES[file_id][1])
        return record

    store.read_file_record.side_effect = _record
    store.read_file.side_effect = lambda file_id, **_kwargs: BytesIO(_FILES[file_id][1])
    return store


@pytest.fixture
def connector(monkeypatch: pytest.MonkeyPatch) -> LocalFileConnector:
    monkeypatch.setattr(file_connector, "get_default_file_store", _store)
    monkeypatch.setattr(
        file_connector,
        "extract_text_and_images",
        lambda file, **_kwargs: ExtractionResult(
            text_content=file.read().decode(), embedded_images=[], metadata={}
        ),
    )
    monkeypatch.setattr(
        file_connector,
        "tabular_file_to_sections",
        MagicMock(side_effect=RuntimeError("staging failed")),
    )
    conn = LocalFileConnector(file_locations=list(_FILES))
    conn.set_raw_file_callback(MagicMock())
    return conn


def _listed_ids(conn: LocalFileConnector) -> set[str]:
    return {
        item.id
        for batch in conn.retrieve_all_slim_docs()
        for item in batch
        if isinstance(item, SlimDocument)
    }


def test_prune_listing_keeps_a_file_that_failed_to_process(
    connector: LocalFileConnector,
) -> None:
    indexed_ids = {
        doc.id
        for batch in connector.load_from_state()
        for doc in batch
        if isinstance(doc, Document)
    }
    assert indexed_ids == {file_document_id("txt-file", None)}

    assert _listed_ids(connector) == {
        file_document_id("csv-file", None),
        file_document_id("txt-file", None),
    }


def test_prune_listing_raises_when_metadata_is_unreadable(
    monkeypatch: pytest.MonkeyPatch, connector: LocalFileConnector
) -> None:
    store = MagicMock()
    store.read_file.side_effect = RuntimeError("missing")
    monkeypatch.setattr(metadata, "get_default_file_store", lambda: store)
    connector._zip_metadata_file_id = "meta"

    with pytest.raises(ZipMetadataError):
        _listed_ids(connector)


def test_prune_listing_of_no_files_is_empty(connector: LocalFileConnector) -> None:
    connector.file_locations = []

    assert _listed_ids(connector) == set()
