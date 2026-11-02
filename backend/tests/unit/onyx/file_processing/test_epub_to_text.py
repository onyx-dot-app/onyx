import io
import zipfile

import pytest

from onyx.file_processing.extract_file_text import epub_to_text

_CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf"
              media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

_PACKAGE = """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Probe</dc:title><dc:identifier id="id">probe</dc:identifier>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml"
          properties="nav"/>
    <item id="c1" href="{first_href}" media-type="application/xhtml+xml"/>
    <item id="c2" href="chapter2.xhtml" media-type="application/xhtml+xml"/>
    <item id="c3" href="chapter3.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="c1"/><itemref idref="c2"/><itemref idref="c3"/>
  </spine>
</package>"""


def _page(body: str) -> str:
    return f"<html><body><p>{body}</p></body></html>"


def _epub_bytes(
    *,
    with_package: bool = True,
    first_name: str = "chapter1.xhtml",
    first_href: str = "chapter1.xhtml",
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("mimetype", "application/epub+zip")
        if with_package:
            archive.writestr("META-INF/container.xml", _CONTAINER)
            archive.writestr(
                "OEBPS/content.opf", _PACKAGE.format(first_href=first_href)
            )
        archive.writestr("OEBPS/nav.xhtml", _page("TABLE OF CONTENTS"))
        # Written in an order the spine does not follow.
        archive.writestr("OEBPS/chapter3.xhtml", _page("CHAPTER THREE BODY"))
        archive.writestr("OEBPS/" + first_name, _page("CHAPTER ONE BODY"))
        archive.writestr("OEBPS/chapter2.xhtml", _page("CHAPTER TWO BODY"))
    return buffer.getvalue()


def test_chapters_come_out_in_reading_order() -> None:
    """infolist() is storage order, which an EPUB promises nothing about."""
    text = epub_to_text(io.BytesIO(_epub_bytes()))

    assert [line for line in text.splitlines() if line] == [
        "CHAPTER ONE BODY",
        "CHAPTER TWO BODY",
        "CHAPTER THREE BODY",
    ]


def test_the_navigation_document_is_not_content() -> None:
    """The table of contents is not in the spine, so it is not part of the book."""
    assert "TABLE OF CONTENTS" not in epub_to_text(io.BytesIO(_epub_bytes()))


def test_a_percent_encoded_href_resolves() -> None:
    """A manifest href is a URL reference, not a file name."""
    text = epub_to_text(
        io.BytesIO(
            _epub_bytes(
                first_name="chapter one.xhtml", first_href="chapter%20one.xhtml"
            )
        )
    )

    assert "CHAPTER ONE BODY" in text


def test_one_damaged_chapter_does_not_cost_the_book() -> None:
    """zipfile raises BadZipFile on a failed CRC, which is not a KeyError."""
    raw = bytearray(_epub_bytes())
    # The archive is stored uncompressed, so the payload is in there verbatim and
    # changing a byte leaves the stored CRC-32 pointing at the old content.
    raw[raw.index(b"CHAPTER TWO BODY")] = ord("X")
    damaged = bytes(raw)

    with (
        zipfile.ZipFile(io.BytesIO(damaged)) as archive,
        pytest.raises(zipfile.BadZipFile),
    ):
        archive.read("OEBPS/chapter2.xhtml")

    text = epub_to_text(io.BytesIO(damaged))

    assert "CHAPTER ONE BODY" in text
    assert "CHAPTER THREE BODY" in text


def test_a_spine_entry_with_no_file_is_skipped() -> None:
    """A spine can name a document the archive does not carry."""
    raw = _epub_bytes()
    buffer = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(raw)) as source,
        zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as target,
    ):
        for item in source.infolist():
            if item.filename == "OEBPS/chapter2.xhtml":
                continue
            target.writestr(item.filename, source.read(item.filename))

    text = epub_to_text(io.BytesIO(buffer.getvalue()))

    assert "CHAPTER ONE BODY" in text
    assert "CHAPTER THREE BODY" in text


def test_an_archive_without_a_package_document_still_reads() -> None:
    """Without a spine there is nothing to order by, so scan as before."""
    text = epub_to_text(io.BytesIO(_epub_bytes(with_package=False)))

    assert "CHAPTER ONE BODY" in text
    assert "CHAPTER TWO BODY" in text
    assert "CHAPTER THREE BODY" in text
