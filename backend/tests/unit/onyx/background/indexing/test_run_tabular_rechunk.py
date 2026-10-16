"""Guards for the tabular re-chunk migration's document rebuild.

The migration re-runs the indexing pipeline over documents nobody changed, so
`_upsert_documents_in_db` writes the rebuilt document back over a row that was
already correct. Anything the rebuild drops is destroyed, quietly, across the
whole corpus. These tests pin the fields that must survive.
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
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    experts_from_stores_representations,
    get_experts_stores_representations,
)
from onyx.connectors.models import (
    Document,
    TabularSection,
    convert_metadata_dict_to_list_of_strings,
)
from onyx.db.models import Document as DbDocument
from onyx.file_processing.file_types import SPREADSHEET_MIME_TYPE

_CSV = b"region,sales\nnorth,10\nsouth,20\n"


def _db_doc() -> DbDocument:
    return DbDocument(
        id="doc-1",
        semantic_id="quarterly.csv",
        link="https://example.com/quarterly.csv",
        file_id="file-abc",
        doc_metadata={"owner_team": "finance"},
        parent_hierarchy_node_id=7,
        primary_owners=["Ada Lovelace"],
        secondary_owners=["Grace Hopper"],
        from_ingestion_api=False,
    )


def _head() -> MagicMock:
    head = MagicMock()
    head.source_type = DocumentSource.FILE.value
    head.title = "Quarterly numbers"
    head.metadata_list = convert_metadata_dict_to_list_of_strings(
        {"department": "finance", "year": "2026"}
    )
    return head


def _stage(content: IO[bytes], content_type: str) -> str:  # noqa: ARG001
    """Stands in for the file-store staging callback."""
    return "staged-csv-1"


def _rebuild() -> Document:
    file_store = MagicMock()
    file_store.read_file.return_value = BytesIO(_CSV)
    with patch(
        "onyx.background.indexing.run_tabular_rechunk.get_default_file_store",
        return_value=file_store,
    ):
        return _rebuild_document(
            db_doc=_db_doc(),
            head=_head(),
            stage=_stage,
            file_type="text/csv",
            parent_hierarchy_raw_node_id="folder-123",
        )


def test_owners_round_trip_through_their_stored_form() -> None:
    """The upsert writes owners back as their string form. If the rebuild did
    not round-trip, every re-chunked document would lose its owners."""
    stored = ["Ada Lovelace", "Grace Hopper"]
    assert (
        get_experts_stores_representations(experts_from_stores_representations(stored))
        == stored
    )
    assert experts_from_stores_representations(None) is None
    assert experts_from_stores_representations([]) is None


def test_rebuild_keeps_the_fields_the_upsert_would_overwrite() -> None:
    doc = _rebuild()

    # Carried from the row: the upsert's update_set writes all of these.
    assert doc.file_id == "file-abc"
    assert doc.doc_metadata == {"owner_team": "finance"}
    assert doc.parent_hierarchy_node_id == 7
    assert doc.semantic_identifier == "quarterly.csv"
    assert get_experts_stores_representations(doc.primary_owners) == ["Ada Lovelace"]

    # Recovered from the stored chunk: Postgres does not keep either.
    assert doc.title == "Quarterly numbers"
    assert doc.metadata == {"department": "finance", "year": "2026"}
    assert doc.source == DocumentSource.FILE


def test_rebuild_carries_the_raw_hierarchy_id() -> None:
    """The adapter resolves ancestors from the raw id, not the resolved one.
    Without it a rebuilt document drops out of folder-scoped search."""
    doc = _rebuild()
    assert doc.parent_hierarchy_raw_node_id == "folder-123"
    assert doc.parent_hierarchy_node_id == 7


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


def test_rebuild_names_an_extensionless_document_from_its_stored_type() -> None:
    file_store = MagicMock()
    file_store.read_file.return_value = BytesIO(_CSV)
    db_doc = _db_doc()
    db_doc.semantic_id = "Q3 Budget"
    with patch(
        "onyx.background.indexing.run_tabular_rechunk.get_default_file_store",
        return_value=file_store,
    ):
        doc = _rebuild_document(
            db_doc=db_doc,
            head=_head(),
            stage=_stage,
            file_type="text/csv",
            parent_hierarchy_raw_node_id=None,
        )
    assert doc.semantic_identifier == "Q3 Budget"
    assert isinstance(doc.sections[0], TabularSection)


def test_rebuild_leaves_external_access_unset() -> None:
    """With no document carrying external_access, upsert_documents leaves the
    ACL columns alone. Setting it here would wipe perm-synced access."""
    assert _rebuild().external_access is None


def test_rebuild_sections_come_from_the_stored_workbook() -> None:
    doc = _rebuild()
    assert [type(section) for section in doc.sections] == [TabularSection]
    section = doc.sections[0]
    assert isinstance(section, TabularSection)
    assert section.csv_file_id == "staged-csv-1"
    assert section.link == "https://example.com/quarterly.csv"
