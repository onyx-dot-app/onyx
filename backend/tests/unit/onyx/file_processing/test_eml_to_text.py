import base64
import io

from onyx.file_processing.extract_file_text import eml_to_text

_BODY = "Quarterly revenue rose to 12.4 million euros.\r\nContact: Ana Mueller.\r\n"
_HEADERS = (
    "From: sender@example.com\r\n"
    "To: recipient@example.com\r\n"
    "Subject: Q3\r\n"
    "MIME-Version: 1.0\r\n"
)


def _eml(transfer_encoding: str, body: str, charset: str = "utf-8") -> io.BytesIO:
    raw = (
        _HEADERS
        + f"Content-Type: text/plain; charset={charset}\r\n"
        + f"Content-Transfer-Encoding: {transfer_encoding}\r\n\r\n"
        + body
    )
    return io.BytesIO(raw.encode(charset))


def test_base64_body_is_decoded() -> None:
    """A base64 body reached the index as base64 rather than as its text."""
    encoded = base64.b64encode(_BODY.encode()).decode() + "\r\n"
    assert "Quarterly revenue rose to 12.4 million euros." in eml_to_text(
        _eml("base64", encoded)
    )


def test_quoted_printable_body_is_decoded() -> None:
    """A quoted-printable body kept its =0D=0A and =C3=BC escapes."""
    text = eml_to_text(
        _eml(
            "quoted-printable",
            "Quarterly revenue rose to 12.4 million euros."
            "=0D=0AContact: Ana M=C3=BCller.=0D=0A\r\n",
        )
    )

    assert "Contact: Ana Müller." in text
    assert "=0D=0A" not in text
    assert "=C3=BC" not in text


def test_quoted_printable_body_honours_the_declared_charset() -> None:
    """The bytes a transfer encoding yields mean nothing without the charset."""
    text = eml_to_text(
        _eml("quoted-printable", "Ana M=FCller\r\n", charset="iso-8859-1")
    )

    assert "Ana Müller" in text


def test_plain_body_is_unchanged() -> None:
    """7bit and 8bit parts are already text and must not be re-encoded."""
    assert _BODY.replace("\r\n", "\n") in eml_to_text(_eml("7bit", _BODY))


def test_body_without_a_transfer_encoding_header_is_unchanged() -> None:
    """The header is optional; its absence means the part was never encoded."""
    raw = (
        _HEADERS + "Content-Type: text/plain; charset=utf-8\r\n\r\n" + _BODY
    ).encode()

    assert "Quarterly revenue rose to 12.4 million euros." in eml_to_text(
        io.BytesIO(raw)
    )


def test_an_html_only_body_is_read() -> None:
    """A mail with no plain-text alternative used to reach the index empty."""
    raw = (
        _HEADERS
        + "Content-Type: text/html; charset=utf-8\r\n"
        + "Content-Transfer-Encoding: 7bit\r\n\r\n"
        + "<html><body><p>Quarterly revenue rose to 12.4 million euros.</p>"
        + "<p>Contact: Ana Mueller.</p></body></html>\r\n"
    ).encode()

    text = eml_to_text(io.BytesIO(raw))

    assert "Quarterly revenue rose to 12.4 million euros." in text
    assert "Contact: Ana Mueller." in text
    assert "<p>" not in text


def test_an_html_only_body_is_decoded_first() -> None:
    """The HTML part carries a transfer encoding of its own."""
    encoded = base64.b64encode(
        b"<html><body><p>Quarterly revenue rose to 12.4 million euros.</p></body></html>"
    ).decode()
    raw = (
        _HEADERS
        + "Content-Type: text/html; charset=utf-8\r\n"
        + "Content-Transfer-Encoding: base64\r\n\r\n"
        + encoded
        + "\r\n"
    ).encode()

    assert "Quarterly revenue rose to 12.4 million euros." in eml_to_text(
        io.BytesIO(raw)
    )


def test_an_html_part_is_ignored_when_there_is_plain_text() -> None:
    """The plain half of a multipart/alternative still wins."""
    raw = (
        _HEADERS
        + 'Content-Type: multipart/alternative; boundary="b1"\r\n\r\n'
        + "--b1\r\n"
        + "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        + "PLAIN WINS\r\n"
        + "--b1\r\n"
        + "Content-Type: text/html; charset=utf-8\r\n\r\n"
        + "<p>HTML LOSES</p>\r\n"
        + "--b1--\r\n"
    ).encode()

    text = eml_to_text(io.BytesIO(raw))

    assert "PLAIN WINS" in text
    assert "HTML LOSES" not in text


def test_multipart_alternative_reads_the_plain_part() -> None:
    """The plain half of a multipart/alternative carries its own encoding."""
    raw = (
        _HEADERS
        + 'Content-Type: multipart/alternative; boundary="b1"\r\n\r\n'
        + "--b1\r\n"
        + "Content-Type: text/plain; charset=utf-8\r\n"
        + "Content-Transfer-Encoding: base64\r\n\r\n"
        + base64.b64encode(_BODY.encode()).decode()
        + "\r\n--b1\r\n"
        + "Content-Type: text/html; charset=utf-8\r\n\r\n"
        + "<p>ignored</p>\r\n"
        + "--b1--\r\n"
    ).encode()

    text = eml_to_text(io.BytesIO(raw))

    assert "Quarterly revenue rose to 12.4 million euros." in text
    assert "ignored" not in text


def test_a_text_attachment_does_not_replace_an_html_body() -> None:
    """The attachment is indexed as before, and the HTML body next to it."""
    raw = (
        _HEADERS
        + 'Content-Type: multipart/mixed; boundary="b1"\r\n\r\n'
        + "--b1\r\n"
        + "Content-Type: text/html; charset=utf-8\r\n\r\n"
        + "<p>The body of the mail.</p>\r\n"
        + "--b1\r\n"
        + "Content-Type: text/plain; charset=utf-8\r\n"
        + 'Content-Disposition: attachment; filename="notes.txt"\r\n\r\n'
        + "Notes from the attachment.\r\n"
        + "--b1--\r\n"
    ).encode()

    text = eml_to_text(io.BytesIO(raw))

    assert "The body of the mail." in text
    assert "Notes from the attachment." in text
    assert text.index("The body of the mail.") < text.index(
        "Notes from the attachment."
    )
