"""Guards that .eml bodies are decoded, HTML-only mail is not empty, and attachments are read.

Each test is written so it FAILS against the previous implementation rather than merely
passing against this one:

* the decode tests assert the plaintext is present AND that the base64 form is absent, so a
  no-op would fail on the second assertion;
* the HTML test uses a message with no text/plain part at all, which previously produced "";
* the attachment tests assert on content that exists only inside the attachment.
"""

import base64
import io
import zipfile

from onyx.file_processing.extract_file_text import eml_to_text


def _message(headers: str, body: str) -> io.BytesIO:
    return io.BytesIO((headers + "\r\n" + body + "\r\n").encode())


def _b64_message(body: str, content_type: str = "text/plain") -> io.BytesIO:
    encoded = base64.b64encode(body.encode()).decode()
    return _message(
        "From: sender@example.com\r\n"
        "To: recipient@example.com\r\n"
        "Subject: Test\r\n"
        "MIME-Version: 1.0\r\n"
        f'Content-Type: {content_type}; charset="utf-8"\r\n'
        "Content-Transfer-Encoding: base64\r\n",
        encoded,
    )


def test_base64_body_is_decoded() -> None:
    body = "Total contract value is 12345.67 for the period."
    out = eml_to_text(_b64_message(body))

    assert "12345.67" in out
    assert base64.b64encode(body.encode()).decode() not in out, (
        "the encoded form must not survive into the output — asserting only on the "
        "decoded text would pass on an implementation that emits both"
    )


def test_quoted_printable_body_is_decoded() -> None:
    raw = _message(
        "From: sender@example.com\r\n"
        "MIME-Version: 1.0\r\n"
        'Content-Type: text/plain; charset="utf-8"\r\n'
        "Content-Transfer-Encoding: quoted-printable\r\n",
        "Rate is 95 =E2=82=AC per hour",
    )
    out = eml_to_text(raw)

    assert "95 € per hour" in out
    assert "=E2=82=AC" not in out


def test_seven_bit_body_is_unchanged() -> None:
    """The common case must not regress."""
    raw = _message(
        "From: sender@example.com\r\n"
        "MIME-Version: 1.0\r\n"
        'Content-Type: text/plain; charset="utf-8"\r\n',
        "Plain body, no transfer encoding.",
    )
    assert "Plain body, no transfer encoding." in eml_to_text(raw)


def test_unknown_charset_still_yields_text() -> None:
    """An unrecognised charset label is not a reason to lose the part."""
    raw = _message(
        "From: sender@example.com\r\n"
        "MIME-Version: 1.0\r\n"
        'Content-Type: text/plain; charset="definitely-not-a-charset"\r\n',
        "Fallback body 4242",
    )
    assert "4242" in eml_to_text(raw)


def test_html_only_mail_is_not_empty() -> None:
    """Previously returned "" — there is no text/plain part to fall back to."""
    out = eml_to_text(
        _b64_message("<html><body><p>Invoice 9911 is attached</p></body></html>", "text/html")
    )

    assert "Invoice 9911" in out


def test_plain_text_wins_over_html_when_both_are_present() -> None:
    """HTML is a fallback, not a preference: ordinary multipart/alternative is unaffected."""
    raw = _message(
        "From: sender@example.com\r\n"
        "MIME-Version: 1.0\r\n"
        'Content-Type: multipart/alternative; boundary="B"\r\n',
        "--B\r\n"
        'Content-Type: text/plain; charset="utf-8"\r\n\r\n'
        "PLAIN-MARKER\r\n"
        "--B\r\n"
        'Content-Type: text/html; charset="utf-8"\r\n\r\n'
        "<html><body>HTML-MARKER</body></html>\r\n"
        "--B--",
    )
    out = eml_to_text(raw)

    assert "PLAIN-MARKER" in out
    assert "HTML-MARKER" not in out


def _with_attachment(filename: str, blob: bytes, content_type: str) -> io.BytesIO:
    return _message(
        "From: sender@example.com\r\n"
        "MIME-Version: 1.0\r\n"
        'Content-Type: multipart/mixed; boundary="B"\r\n',
        "--B\r\n"
        'Content-Type: text/plain; charset="utf-8"\r\n\r\n'
        "See attached.\r\n"
        "--B\r\n"
        f"Content-Type: {content_type}\r\n"
        f'Content-Disposition: attachment; filename="{filename}"\r\n'
        "Content-Transfer-Encoding: base64\r\n\r\n"
        + base64.b64encode(blob).decode()
        + "\r\n--B--",
    )


def test_attachment_text_is_extracted() -> None:
    raw = _with_attachment(
        "terms.txt", b"Payment terms are Net 45 days.", "text/plain"
    )
    out = eml_to_text(raw)

    assert "See attached." in out
    assert "Net 45 days" in out, "the body is a covering note; the substance is in the file"
    assert "[attachment: terms.txt]" in out


def test_attached_text_is_not_counted_twice() -> None:
    """A text/plain part with an attachment disposition must not be read by the body loop."""
    raw = _with_attachment("notes.txt", b"UNIQUE-TOKEN-7731", "text/plain")

    assert eml_to_text(raw).count("UNIQUE-TOKEN-7731") == 1


def test_attachment_with_unlisted_extension_is_skipped() -> None:
    raw = _with_attachment("payload.bin", b"BINARY-MARKER", "application/octet-stream")
    out = eml_to_text(raw)

    assert "See attached." in out
    assert "BINARY-MARKER" not in out


def test_unreadable_attachment_does_not_fail_the_message() -> None:
    """A truncated file is a log line, not an exception — the body must still index."""
    raw = _with_attachment("broken.docx", b"not really a docx", "application/octet-stream")

    assert "See attached." in eml_to_text(raw)


def test_oversized_attachment_is_skipped_without_reading_it() -> None:
    from onyx.file_processing.extract_file_text import EML_ATTACHMENT_MAX_BYTES

    oversized = b"x" * (EML_ATTACHMENT_MAX_BYTES + 1)
    raw = _with_attachment("huge.txt", oversized, "text/plain")
    out = eml_to_text(raw)

    assert "See attached." in out
    assert "xxxx" not in out


def test_nested_eml_is_not_followed() -> None:
    """One level only — a forwarded chain must not expand without bound."""
    inner = (
        "From: inner@example.com\r\n"
        'Content-Type: text/plain; charset="utf-8"\r\n\r\n'
        "INNER-MARKER\r\n"
    ).encode()
    raw = _with_attachment("forwarded.eml", inner, "message/rfc822")

    assert "INNER-MARKER" not in eml_to_text(raw)


def test_xlsx_attachment_is_read() -> None:
    """The case the allowlist exists for: a spreadsheet carrying the figures."""
    buf = io.BytesIO()
    try:
        from openpyxl import Workbook
    except ImportError:  # pragma: no cover - openpyxl is a hard dependency of the image
        return
    wb = Workbook()
    wb.active["A1"] = "Line Item"
    wb.active["B1"] = "Annual Cost"
    wb.active["A2"] = "Backup Software"
    wb.active["B2"] = 650
    wb.save(buf)

    raw = _with_attachment(
        "costs.xlsx",
        buf.getvalue(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    out = eml_to_text(raw)

    assert "Backup Software" in out
    assert "650" in out


def test_a_plain_zip_is_not_treated_as_an_attachment() -> None:
    """get_file_ext, not content sniffing, decides — and .zip is not on the allowlist."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("inside.txt", "ZIP-MARKER")
    raw = _with_attachment("bundle.zip", buf.getvalue(), "application/zip")

    assert "ZIP-MARKER" not in eml_to_text(raw)


def test_the_allowlist_only_promises_what_the_parser_handles() -> None:
    """An entry the local parser cannot read is worse than no entry: the attachment is
    accepted, raises, and is silently skipped — or, for .htm, falls through to the raw-text
    reader and indexes markup."""
    from onyx.file_processing.extract_file_text import EML_ATTACHMENT_EXTENSIONS
    from onyx.file_processing.file_types import OnyxFileExtensions

    unhandled = EML_ATTACHMENT_EXTENSIONS - OnyxFileExtensions.TEXT_AND_DOCUMENT_EXTENSIONS
    assert not unhandled, f"allowlist promises extensions no parser accepts: {unhandled}"


def test_the_allowlist_does_not_admit_nested_mail() -> None:
    """extract_file_text_locally maps .eml to eml_to_text, so admitting .eml here would make
    attachment extraction recursive with no depth bound."""
    from onyx.file_processing.extract_file_text import EML_ATTACHMENT_EXTENSIONS

    assert ".eml" not in EML_ATTACHMENT_EXTENSIONS
