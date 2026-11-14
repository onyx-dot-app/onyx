"""PDF text extraction with PDFium.

`read_pdf_file` runs this in a fresh child process for each PDF, and the child
imports only the module that holds the function. Keep this module's imports
light: importing `extract_file_text` costs about a CPU-second, which every PDF
would pay again.
"""

import psutil

TEXT_SECTION_SEPARATOR = "\n\n"

# PDFium holds every page's fonts until the document closes, so a scan with a
# distinct non-embedded font per page grows tens of MiB a page. Past this
# budget the document is reopened before each page.
PDFIUM_REOPEN_RSS_GROWTH_BYTES = 256 * 1024 * 1024


def extract_pdf_text_pdfium(file_bytes: bytes, password: str | None) -> str:
    """Extract all text from a PDF via pypdfium2 (PDFium/C).

    PDFium releases the GIL while parsing, so a large or complex PDF can't pin
    a worker thread or stall the indexing heartbeat during text extraction.
    """
    import pypdfium2 as pdfium

    process = psutil.Process()
    pdf = pdfium.PdfDocument(file_bytes, password=password)
    rss_at_open = process.memory_info().rss
    try:
        page_texts: list[str] = []
        for index in range(len(pdf)):
            # RSS does not drop after a close, so a reset baseline lets the process
            # keep climbing. Kept fixed, every page past the budget reopens.
            if process.memory_info().rss - rss_at_open > PDFIUM_REOPEN_RSS_GROWTH_BYTES:
                pdf.close()
                pdf = pdfium.PdfDocument(file_bytes, password=password)
            page = pdf[index]
            # Per-page try/finally so a get_textpage() failure still closes the
            # native page handle instead of leaking it until GC.
            try:
                textpage = page.get_textpage()
                try:
                    page_texts.append(textpage.get_text_range())
                finally:
                    textpage.close()
            finally:
                page.close()
        return TEXT_SECTION_SEPARATOR.join(page_texts)
    finally:
        pdf.close()
