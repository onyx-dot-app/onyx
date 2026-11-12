import pytest
from pydantic import ValidationError

from onyx.connectors.models import Document, DocumentBase, TextSection


def test_from_base_keeps_source_type_and_size() -> None:
    base = DocumentBase(
        id="doc-1",
        sections=[TextSection(text="hello")],
        semantic_identifier="report.pdf",
        metadata={},
        source_mime_type="application/pdf",
        source_size_bytes=2048,
    )

    document = Document.from_base(base)

    assert document.source_mime_type == "application/pdf"
    assert document.source_size_bytes == 2048


@pytest.mark.parametrize("size_bytes", [0, 2**63 - 1])
def test_source_size_accepts_the_column_bounds(size_bytes: int) -> None:
    base = DocumentBase(
        id="doc-1",
        sections=[TextSection(text="hello")],
        semantic_identifier="report.pdf",
        metadata={},
        source_size_bytes=size_bytes,
    )

    assert base.source_size_bytes == size_bytes


@pytest.mark.parametrize("size_bytes", [-1, 2**63])
def test_source_size_rejects_values_outside_the_column(size_bytes: int) -> None:
    with pytest.raises(ValidationError):
        DocumentBase(
            id="doc-1",
            sections=[TextSection(text="hello")],
            semantic_identifier="report.pdf",
            metadata={},
            source_size_bytes=size_bytes,
        )
