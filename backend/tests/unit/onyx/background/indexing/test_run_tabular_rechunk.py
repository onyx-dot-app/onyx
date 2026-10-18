"""Guards for the tabular re-chunk migration's document rebuild.

The rebuild is assembled from the stored row and the document's own stored
chunk, not from the connector. Whatever it leaves out is dropped from the
index for every spreadsheet in the corpus, so these tests pin what must
survive the round trip.
"""

from io import BytesIO
from itertools import chain, repeat
from types import SimpleNamespace
from typing import IO, Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.background.indexing.run_tabular_rechunk import (
    _rebuild_document,
    _tabular_file_name,
    run_tabular_rechunk,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import (
    Document,
    TabularSection,
    convert_metadata_dict_to_list_of_strings,
)
from onyx.db.models import Document as DbDocument
from onyx.file_processing.file_types import SPREADSHEET_MIME_TYPE

_CSV = b"region,sales\nnorth,10\nsouth,20\n"


def _stage(content: IO[bytes], content_type: str) -> str:  # noqa: ARG001
    """Stands in for the file-store staging callback."""
    return "staged-csv-1"


def _rebuild(semantic_id: str = "quarterly.csv") -> Document:
    db_doc = DbDocument(
        id="doc-1",
        semantic_id=semantic_id,
        link="https://example.com/quarterly.csv",
        file_id="file-abc",
        parent_hierarchy_node_id=7,
        primary_owners=["Ada Lovelace"],
        secondary_owners=["Grace Hopper"],
        from_ingestion_api=False,
    )
    head = MagicMock()
    head.source_type = DocumentSource.FILE.value
    head.title = "Quarterly numbers"
    head.metadata_list = convert_metadata_dict_to_list_of_strings(
        {"department": "finance", "year": "2026"}
    )

    file_store = MagicMock()
    file_store.read_file.return_value = BytesIO(_CSV)
    with patch(
        "onyx.background.indexing.run_tabular_rechunk.get_default_file_store",
        return_value=file_store,
    ):
        return _rebuild_document(
            db_doc=db_doc, head=head, stage=_stage, file_type="text/csv"
        )


def test_the_rebuild_carries_everything_the_index_write_reads() -> None:
    doc = _rebuild()

    # From the row.
    assert doc.semantic_identifier == "quarterly.csv"
    assert doc.parent_hierarchy_node_id == 7
    # Off the document, not the row, so an unset value is a silent loss.
    assert [o.display_name for o in doc.primary_owners or []] == ["Ada Lovelace"]
    assert [o.display_name for o in doc.secondary_owners or []] == ["Grace Hopper"]

    # From the stored chunk: Postgres keeps neither.
    assert doc.title == "Quarterly numbers"
    assert doc.metadata == {"department": "finance", "year": "2026"}
    assert doc.source == DocumentSource.FILE

    # From the stored workbook, staged again for the chunker to stream.
    section = doc.sections[0]
    assert isinstance(section, TabularSection)
    assert section.csv_file_id == "staged-csv-1"
    assert section.link == "https://example.com/quarterly.csv"


def test_tabular_file_name_supplies_a_missing_extension() -> None:
    """A native Google Sheet keeps its own name, which usually has no
    extension, so the stored MIME type has to supply one for the reader to
    dispatch on."""
    assert _tabular_file_name("Q3 Budget", SPREADSHEET_MIME_TYPE) == "Q3 Budget.xlsx"
    assert _tabular_file_name("Q3 Budget", "text/csv") == "Q3 Budget.csv"
    # A name that already says what it is wins over the stored type.
    assert _tabular_file_name("report.csv", SPREADSHEET_MIME_TYPE) == "report.csv"
    with pytest.raises(ValueError):
        _tabular_file_name("notes", "application/pdf")
    # And the rebuild routes an extensionless name through it.
    assert _rebuild(semantic_id="Q3 Budget").semantic_identifier == "Q3 Budget"


class _FakeTarget:
    def __init__(self, index: int) -> None:
        self.document = SimpleNamespace(id=f"doc-{index:02d}")
        self.connector_id = 1
        self.credential_id = 1
        self.file_type = "text/csv"


def _run_against(index_names: list[str], pages_before_the_end: int) -> Any:
    """Runs the scan with `get_current_search_settings` answering in turn."""
    names = chain(index_names, repeat(index_names[-1]))
    pages = 0

    def settings(_db_session: object) -> SimpleNamespace:
        return SimpleNamespace(index_name=next(names), id=1)

    def targets(*args: Any, **kwargs: Any) -> list[_FakeTarget]:  # noqa: ARG001
        nonlocal pages
        pages += 1
        # A short page ends the scan, as a real one does at the table's end.
        return [
            _FakeTarget(i) for i in range(16 if pages < pages_before_the_end else 3)
        ]

    def batch(
        targets: list[_FakeTarget],
        **kwargs: Any,  # noqa: ARG001
    ) -> tuple[int, list[str]]:
        return len(targets), []

    module = "onyx.background.indexing.run_tabular_rechunk"
    with (
        patch(f"{module}.get_current_search_settings", settings),
        patch(f"{module}.get_oversized_tabular_documents", targets),
        patch(f"{module}._rechunk_batch", batch),
        patch(f"{module}.get_session_with_current_tenant"),
        patch(f"{module}.DefaultIndexingEmbedder"),
        patch(f"{module}.build_opensearch_document_index"),
    ):
        result = run_tabular_rechunk(
            tenant_id="t", after_doc_id=None, on_batch=lambda: None
        )
    return result, pages


def test_the_scan_stops_when_the_live_index_is_swapped() -> None:
    """An INSTANT swap retires the index this run holds. Writing on would
    replace chunks in the index being dropped while lowering the shared
    chunk_count, stranding the new live index oversized and unselectable.
    """
    result, pages = _run_against(["idx-a", "idx-a", "idx-a", "idx-b"], 99)

    assert pages == 2
    # Not "complete": the pass has to be resumable, not marked done.
    assert not result.finished
    assert result.last_document_id == "doc-15"


def test_an_undisturbed_scan_still_runs_to_the_end() -> None:
    result, pages = _run_against(["idx-a"], pages_before_the_end=3)
    assert pages == 3
    assert result.finished
