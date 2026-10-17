"""Guards for the tabular re-chunk migration's document rebuild.

The migration re-runs the indexing pipeline over documents nobody changed, so
`_upsert_documents_in_db` writes the rebuilt document back over a row that was
already correct. Anything the rebuild drops is destroyed, quietly, across the
whole corpus. These tests pin the fields that must survive.
"""

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from io import BytesIO
from types import SimpleNamespace
from typing import IO, Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.background.indexing import run_tabular_rechunk as rechunk_module
from onyx.background.indexing.run_tabular_rechunk import (
    _rebuild_document,
    _tabular_file_name,
    retry_tabular_rechunk,
)
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
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
        )


def test_rebuild_keeps_the_fields_the_upsert_would_overwrite() -> None:
    doc = _rebuild()

    # Carried from the row: the upsert's update_set writes all of these.
    assert doc.parent_hierarchy_node_id == 7
    assert doc.semantic_identifier == "quarterly.csv"

    # Recovered from the stored chunk: Postgres does not keep either.
    assert doc.title == "Quarterly numbers"
    assert doc.metadata == {"department": "finance", "year": "2026"}
    assert doc.source == DocumentSource.FILE

    # The chunk writer reads these off the document, not off the row.
    assert [o.display_name for o in doc.primary_owners or []] == ["Ada Lovelace"]
    assert [o.display_name for o in doc.secondary_owners or []] == ["Grace Hopper"]


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
        )
    assert doc.semantic_identifier == "Q3 Budget"
    assert isinstance(doc.sections[0], TabularSection)


def test_rebuild_sections_come_from_the_stored_workbook() -> None:
    doc = _rebuild()
    assert [type(section) for section in doc.sections] == [TabularSection]
    section = doc.sections[0]
    assert isinstance(section, TabularSection)
    assert section.csv_file_id == "staged-csv-1"
    assert section.link == "https://example.com/quarterly.csv"


_QUEUE = [f"doc-{i:03d}" for i in range(40)]


class _FakeTarget:
    def __init__(self, document_id: str) -> None:
        self.document = SimpleNamespace(id=document_id)
        self.connector_id = 1
        self.credential_id = 1
        self.file_type = "text/csv"


@contextmanager
def _retry_harness(
    targets_for: Callable[[Sequence[str]], list[_FakeTarget]],
) -> Iterator[list[str]]:
    """Runs the retry loop against fakes, collecting the ids it processes."""
    processed: list[str] = []

    def fake_page(
        targets: list[_FakeTarget], **kwargs: Any
    ) -> tuple[int, list[str], int]:
        processed.extend(target.document.id for target in targets)
        return len(targets), [], kwargs["batch_num"] + 1

    def fake_targets(
        db_session: object,  # noqa: ARG001
        *,
        document_ids: Sequence[str],
        **kwargs: Any,  # noqa: ARG001
    ) -> list[_FakeTarget]:
        # The queue is walked a page at a time, never sent whole.
        assert len(document_ids) <= INDEX_BATCH_SIZE
        return targets_for(document_ids)

    with (
        patch.object(rechunk_module, "get_tabular_rechunk_retry_targets", fake_targets),
        patch.object(rechunk_module, "_rechunk_page", fake_page),
        patch.object(rechunk_module, "get_session_with_current_tenant"),
        patch.object(rechunk_module, "get_current_search_settings"),
        patch.object(rechunk_module, "DefaultIndexingEmbedder"),
        patch.object(rechunk_module, "build_opensearch_document_index"),
    ):
        yield processed


def test_retry_walks_the_whole_queue_in_order() -> None:
    with _retry_harness(lambda ids: [_FakeTarget(i) for i in ids]) as processed:
        result = retry_tabular_rechunk(
            tenant_id="t", document_ids=_QUEUE, on_batch=lambda: None
        )
    assert processed == _QUEUE
    assert result.remaining_document_ids == []
    assert result.documents_indexed == len(_QUEUE)


def test_retry_keeps_its_tail_when_the_budget_runs_out() -> None:
    """The next tick resumes from the queue, so nothing may be dropped."""
    with _retry_harness(lambda ids: [_FakeTarget(i) for i in ids]) as processed:
        result = retry_tabular_rechunk(
            tenant_id="t",
            document_ids=_QUEUE,
            time_budget_s=-1,
            on_batch=lambda: None,
        )
    assert processed == []
    assert result.remaining_document_ids == _QUEUE


def test_retry_drains_a_queue_whose_documents_are_gone() -> None:
    """A document that lost its file or cc-pair stops matching. It has to drop
    out of the queue, or the pass would never end."""
    with _retry_harness(lambda _: []) as processed:
        result = retry_tabular_rechunk(
            tenant_id="t", document_ids=_QUEUE, on_batch=lambda: None
        )
    assert processed == []
    assert result.remaining_document_ids == []
