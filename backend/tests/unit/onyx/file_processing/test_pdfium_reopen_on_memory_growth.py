"""PDFium text extraction reopens the document before every page once the
process has grown past PDFIUM_REOPEN_RSS_GROWTH_BYTES, so a PDF whose pages
each carry their own font cannot grow the document-level font cache without
bound."""

from itertools import chain, repeat
from pathlib import Path
from unittest.mock import MagicMock, patch

import pypdfium2

from onyx.file_processing import pdfium_text
from onyx.file_processing.pdfium_text import PDFIUM_REOPEN_RSS_GROWTH_BYTES

FIXTURES = Path(__file__).parent / "fixtures"
MIB = 1024 * 1024


def _extract_with_rss(rss_at_open: int, rss_after: int) -> tuple[str, int]:
    """Run the extractor on the two-page fixture with the first RSS reading at
    open and every later reading fixed, and return the text and the number of
    PdfDocument opens."""
    process = MagicMock()
    process.memory_info.side_effect = chain(
        [MagicMock(rss=rss_at_open)], repeat(MagicMock(rss=rss_after))
    )
    with (
        patch.object(pypdfium2, "PdfDocument", wraps=pypdfium2.PdfDocument) as opens,
        patch.object(pdfium_text.psutil, "Process", return_value=process),
    ):
        text = pdfium_text.extract_pdf_text_pdfium(
            (FIXTURES / "multipage.pdf").read_bytes(), None
        )
    return text, opens.call_count


def test_flat_memory_keeps_one_document() -> None:
    text, opens = _extract_with_rss(100 * MIB, 110 * MIB)

    assert opens == 1
    assert "Page one content" in text and "Page two content" in text


def test_growth_past_the_budget_reopens_before_every_page() -> None:
    grown = 100 * MIB + PDFIUM_REOPEN_RSS_GROWTH_BYTES + 1
    text, opens = _extract_with_rss(100 * MIB, grown)

    # The baseline stays at the first open, so both pages reopen. A baseline
    # that reset after the first reopen would open only twice.
    assert opens == 3
    assert "Page one content" in text and "Page two content" in text
