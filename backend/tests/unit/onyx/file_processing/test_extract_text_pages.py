"""extract_text_pages gives the text of each page of a PDF, each slide of a
PowerPoint file and each sheet of a spreadsheet, and any other file as one
text without pages."""

from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import docx
import openpyxl
import pytest
from pptx import Presentation

from onyx.file_processing import extract_file_text
from onyx.file_processing.extract_file_text import PagedText, extract_text_pages

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def no_unstructured_key() -> Iterator[None]:
    with patch.object(extract_file_text, "get_unstructured_api_key", return_value=None):
        yield


def test_a_pdf_has_a_page_for_each_page() -> None:
    with FIXTURES.joinpath("multipage.pdf").open("rb") as pdf:
        extracted = extract_text_pages(pdf, "multipage.pdf")

    assert extracted.paged
    assert len(extracted.pages) == 2
    assert "Page one content" in extracted.pages[0]
    assert "Page two content" in extracted.pages[1]


def test_a_powerpoint_file_has_a_page_for_each_slide() -> None:
    presentation = Presentation()
    for title in ("Herons", "Egrets", "Storks"):
        slide = presentation.slides.add_slide(presentation.slide_layouts[5])
        slide.shapes.title.text = title
    buffer = BytesIO()
    presentation.save(buffer)

    extracted = extract_text_pages(BytesIO(buffer.getvalue()), "birds.pptx")

    assert extracted.paged
    assert [page.strip() for page in extracted.pages] == [
        "# Herons",
        "# Egrets",
        "# Storks",
    ]


def test_a_spreadsheet_has_a_page_for_each_sheet() -> None:
    workbook = openpyxl.Workbook()
    del workbook["Sheet"]
    workbook.create_sheet("Notes")["A1"] = "herons"
    workbook.create_sheet("Empty")
    workbook.create_sheet("Totals")["A1"] = "egrets"
    buffer = BytesIO()
    workbook.save(buffer)

    extracted = extract_text_pages(BytesIO(buffer.getvalue()), "birds.xlsx")

    assert extracted == PagedText(["herons", "", "egrets"], paged=True)


def test_a_word_file_is_one_text_without_pages() -> None:
    document = docx.Document()
    document.add_paragraph("Herons and egrets.")
    buffer = BytesIO()
    document.save(buffer)

    extracted = extract_text_pages(BytesIO(buffer.getvalue()), "birds.docx")

    assert not extracted.paged
    [text] = extracted.pages
    assert "Herons and egrets." in text


def test_a_file_no_parser_reads_has_no_text() -> None:
    extracted = extract_text_pages(BytesIO(bytes(range(256))), "blob.bin")

    assert extracted == PagedText([""], paged=False)


@pytest.mark.parametrize(
    ("markdown", "expected"),
    [
        (
            "Herons without slide markers.\n",
            PagedText(["Herons without slide markers.\n"], paged=False),
        ),
        (
            "Deck notes\n<!-- Slide number: 1 -->\nHerons\n<!-- Slide number: 2 -->\nEgrets\n",
            PagedText(["Deck notes\nHerons\n", "Egrets\n"], paged=True),
        ),
    ],
)
def test_a_powerpoint_file_keeps_text_outside_the_slide_markers(
    markdown: str, expected: PagedText
) -> None:
    with patch.object(extract_file_text, "pptx_to_text", return_value=markdown):
        extracted = extract_text_pages(BytesIO(b"pptx"), "birds.pptx")

    assert extracted == expected
