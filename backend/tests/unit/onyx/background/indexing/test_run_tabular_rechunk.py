"""Guards for the tabular re-chunk migration's document rebuild.

The rebuild is assembled from the stored row and the document's own stored
chunk, not from the connector. Whatever it leaves out is dropped from the
index for every spreadsheet in the corpus, so these tests pin what must
survive the round trip.
"""

from io import BytesIO
from typing import IO
from unittest.mock import MagicMock, patch

import pytest

from onyx.background.indexing.run_tabular_rechunk import (
    _rebuild_document,
    _tabular_file_name,
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
