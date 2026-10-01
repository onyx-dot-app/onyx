"""Coverage for the Content-Disposition helpers in `onyx.file_store.serving`."""

import pytest

from onyx.file_store.serving import build_content_disposition, ensure_filename_extension

PPTX_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)


def test_content_disposition_escapes_quotes_and_separators() -> None:
    header = build_content_disposition("attachment", 'Q3 "final" \\ v2/deck.pptx')

    assert header == (
        'attachment; filename="Q3 _final_ _ v2_deck.pptx"; '
        "filename*=UTF-8''Q3%20_final_%20_%20v2_deck.pptx"
    )


def test_content_disposition_strips_header_injection() -> None:
    header = build_content_disposition("attachment", "deck\r\nSet-Cookie: a=b.pptx")

    assert "\r" not in header
    assert "\n" not in header
    assert header.startswith('attachment; filename="deck__Set-Cookie: a=b.pptx";')


def test_content_disposition_encodes_non_ascii_names() -> None:
    header = build_content_disposition("attachment", "Résumé 報告.docx")

    assert header == (
        'attachment; filename="R_sum_ __.docx"; '
        "filename*=UTF-8''R%C3%A9sum%C3%A9%20%E5%A0%B1%E5%91%8A.docx"
    )
    assert header.isascii()


def test_content_disposition_names_an_empty_filename() -> None:
    assert build_content_disposition("attachment", "  ") == (
        "attachment; filename=\"download\"; filename*=UTF-8''download"
    )


@pytest.mark.parametrize(
    "filename, media_type, expected",
    [
        ("Q3 Deck", PPTX_MIME_TYPE, "Q3 Deck.pptx"),
        ("data", "text/csv", "data.csv"),
        ("Sales v1.2 data", "text/csv", "Sales v1.2 data.csv"),
        ("chart", "image/png;base64", "chart.png"),
        ("Q3 Deck.pptx", PPTX_MIME_TYPE, "Q3 Deck.pptx"),
        ("notes.md", "text/plain", "notes.md"),
        ("blob", "application/octet-stream", "blob"),
        ("blob", "application/x-onyx-unknown", "blob"),
    ],
)
def test_ensure_filename_extension(
    filename: str, media_type: str, expected: str
) -> None:
    assert ensure_filename_extension(filename, media_type) == expected
