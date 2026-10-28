"""Tabular `Document.file_id` regression tests for the Directory connector.

`_process_file` stamps `Document.file_id` with its `file_id` argument for
tabular files ("stage these bytes" signal). The Directory connector passes
its document id there -- a `directory:<source>:<sha>` string that is not a
file-store record. These tests pin the corrected contract:

- a freshly indexed tabular file must not carry the document id as
  `Document.file_id`;
- a genuine staged-file reference (any id other than the document id) must
  survive unchanged;
- non-tabular files (PDF) keep `Document.file_id=None` -- no regression;
- `_process_file` must still be called with `file_id=document_id`, because
  the same argument defines the embedded-image name prefix
  (`<file_id>_embedded_<idx>`).
"""

import uuid
from pathlib import Path
from typing import Any

import pytest

from onyx.connectors.directory.connector import DirectoryConnector
from onyx.connectors.models import Document, TabularSection

_ALLOWED_ROOTS_ENV = "DIRECTORY_CONNECTOR_ALLOWED_ROOTS"


@pytest.fixture(autouse=True)
def _no_unstructured_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep file processing offline: the KV store would hit the real DB."""
    import onyx.file_processing.extract_file_text as extract_file_text

    monkeypatch.setattr(extract_file_text, "get_unstructured_api_key", lambda: None)


def _tracking_stage() -> Any:
    """Offline stand-in for the docprocessing raw-file staging callback."""
    return lambda _content, _content_type: "staged-section-file"


@pytest.fixture
def source_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "docs"
    root.mkdir()
    monkeypatch.setenv(_ALLOWED_ROOTS_ENV, str(tmp_path))
    return root


def _make_connector(root: Path, **kwargs: Any) -> DirectoryConnector:
    kwargs.setdefault("source_id", "docs")
    connector = DirectoryConnector(str(root), **kwargs)
    connector.set_raw_file_callback(_tracking_stage())
    return connector


def _assert_not_document_id(document: Document, document_id: str) -> None:
    assert document.file_id != document_id, (
        "Document.file_id must not be the Directory document id "
        f"({document_id!r} is not a file-store record); got "
        f"{document.file_id!r}."
    )
    assert document.file_id is None


def test_csv_tabular_file_id_is_not_document_id(
    source_root: Path,
) -> None:
    """RED at the unpatched PR head: a CSV carries `file_id=<document_id>`."""
    (source_root / "report.csv").write_text("name,value\nalpha,1\n")
    connector = _make_connector(source_root)

    result = connector._process_path(
        "report.csv", start=None, end=None, apply_time_window=False
    )

    assert isinstance(result, Document), f"expected Document, got {result!r}"
    assert any(isinstance(section, TabularSection) for section in result.sections)
    _assert_not_document_id(result, result.id)


def test_xlsx_tabular_file_id_is_not_document_id(
    source_root: Path,
) -> None:
    """Same contract for a real spreadsheet, exercised through the sheet path."""
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet["A1"] = "name"
    sheet["B1"] = "value"
    sheet["A2"] = "beta"
    sheet["B2"] = "2"
    workbook.save(source_root / "book.xlsx")
    connector = _make_connector(source_root)

    result = connector._process_path(
        "book.xlsx", start=None, end=None, apply_time_window=False
    )

    assert isinstance(result, Document), f"expected Document, got {result!r}"
    assert any(isinstance(section, TabularSection) for section in result.sections)
    _assert_not_document_id(result, result.id)


def _build_pdf(text: str) -> bytes:
    """Minimal valid one-page PDF with a correct xref table."""
    stream = b"BT /F1 24 Tf 72 720 Td (%s) Tj ET" % text.encode()
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length %d>>\nstream\n%s\nendstream" % (len(stream), stream),
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for index, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % index + body + b"\nendobj\n"
    xref_pos = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<</Size %d /Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objs) + 1,
        xref_pos,
    )
    return out


def test_pdf_file_id_contract_unchanged(
    source_root: Path,
) -> None:
    """Non-tabular files keep `Document.file_id=None` (no regression)."""
    (source_root / "doc.pdf").write_bytes(_build_pdf("hello fixture"))
    connector = _make_connector(source_root)

    result = connector._process_path(
        "doc.pdf", start=None, end=None, apply_time_window=False
    )

    assert isinstance(result, Document), f"expected Document, got {result!r}"
    assert result.sections, "PDF must still index with sections"
    assert result.file_id is None


def test_genuine_staged_file_reference_is_preserved(
    source_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real staged-file id (differing from the document id) must survive.

    Simulates a connector path (e.g. a future native-staging variant) where
    the raw bytes were actually persisted and `_process_file` returned the
    staged record id: the fix may only clear the document-id stamp, never a
    genuine reference.
    """
    staged_uuid = str(uuid.uuid4())

    def _staged_file_id_is_real(file_id: str) -> str:
        # A genuine persisted file is keyed by its own record id, which is
        # never equal to the connector document id.
        assert file_id != staged_uuid
        return staged_uuid

    import onyx.connectors.directory.connector as directory_module

    original = directory_module._process_file

    def spy_process_file(*args: Any, **kwargs: Any) -> list[Document]:
        documents = original(*args, **kwargs)
        for document in documents:
            if document.file_id is not None:
                document.file_id = _staged_file_id_is_real(kwargs["file_id"])
        return documents

    monkeypatch.setattr(directory_module, "_process_file", spy_process_file)

    (source_root / "report.csv").write_text("name,value\nalpha,1\n")
    connector = _make_connector(source_root)

    result = connector._process_path(
        "report.csv", start=None, end=None, apply_time_window=False
    )

    assert isinstance(result, Document), f"expected Document, got {result!r}"
    assert result.file_id == staged_uuid


def test_process_file_still_receives_document_id(
    source_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_process_file(file_id=...)` must stay the document id.

    The same argument is the embedded-image name prefix
    (`<file_id>_embedded_<idx>`); the fix must not change what is passed
    in, only what ends up on the Document.
    """
    import onyx.connectors.directory.connector as directory_module

    seen: dict[str, Any] = {}
    original = directory_module._process_file

    def spy_process_file(*args: Any, **kwargs: Any) -> list[Document]:
        seen["file_id"] = kwargs.get("file_id")
        return original(*args, **kwargs)

    monkeypatch.setattr(directory_module, "_process_file", spy_process_file)

    (source_root / "report.csv").write_text("name,value\nalpha,1\n")
    connector = _make_connector(source_root)

    result = connector._process_path(
        "report.csv", start=None, end=None, apply_time_window=False
    )

    assert isinstance(result, Document), f"expected Document, got {result!r}"
    assert seen["file_id"] == result.id
    # The prefix contract: embedded images would be keyed
    # f"{seen['file_id']}_embedded_<idx>" -- defined, not None.
    assert seen["file_id"] is not None
