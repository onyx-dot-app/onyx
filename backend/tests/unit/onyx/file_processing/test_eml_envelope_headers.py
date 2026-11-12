import io

from onyx.file_processing.extract_file_text import eml_to_text


def _eml(headers: str, body: str = "Thank you for the detail, this is approved.") -> io.BytesIO:
    raw = (
        f"{headers}"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        f"{body}\r\n"
    )
    return io.BytesIO(raw.encode())


def test_the_messages_own_sender_is_extracted() -> None:
    text = eml_to_text(_eml("From: Approver One <approver@example.com>\r\n"))
    assert "From: Approver One <approver@example.com>" in text


def test_the_own_sender_precedes_a_quoted_sender_further_down() -> None:
    """A reply carries the quoted headers of the message it answers. Without the envelope the
    only sender in the extracted text is that quoted one, so the nearest sender to the reply's
    own words is a different person."""
    text = eml_to_text(
        _eml(
            "From: Approver One <approver@example.com>\r\n",
            "Thank you for the detail, this is approved.\r\n"
            "\r\n"
            "________________________________\r\n"
            "From: Credit Group Mailbox <credit@other.example>\r\n"
            "Sent: Tuesday, March 31, 2026 8:57 AM\r\n",
        )
    )
    own = text.find("approver@example.com")
    quoted = text.find("credit@other.example")
    assert own != -1, "the reply's own sender is missing"
    assert quoted != -1, "the quoted block was dropped from the body"
    assert own < quoted


def test_to_cc_date_and_subject_are_extracted() -> None:
    text = eml_to_text(
        _eml(
            "From: A <a@example.com>\r\n"
            "To: B <b@example.com>\r\n"
            "Cc: C <c@example.com>\r\n"
            "Date: Tue, 31 Mar 2026 09:14:00 -0400\r\n"
            "Subject: Re: Credit Limit Approval Request\r\n"
        )
    )
    assert "To: B <b@example.com>" in text
    assert "Cc: C <c@example.com>" in text
    assert "Date: Tue, 31 Mar 2026 09:14:00 -0400" in text
    assert "Subject: Re: Credit Limit Approval Request" in text


def test_rfc2047_encoded_sender_is_decoded() -> None:
    text = eml_to_text(_eml("From: =?utf-8?B?SsO2cmcgTcO8bGxlcg==?= <jm@example.com>\r\n"))
    assert "Jörg Müller" in text
    assert "=?utf-8?B?" not in text


def test_a_folded_header_becomes_one_line() -> None:
    text = eml_to_text(
        _eml(
            "From: A <a@example.com>\r\n"
            "Subject: a long subject the mailer\r\n folded across two lines\r\n"
        )
    )
    subject_lines = [ln for ln in text.splitlines() if ln.startswith("Subject:")]
    assert len(subject_lines) == 1
    assert "folded across two lines" in subject_lines[0]


def test_absent_headers_are_omitted_rather_than_emitted_empty() -> None:
    text = eml_to_text(_eml("From: A <a@example.com>\r\n"))
    assert "To:" not in text
    assert "Cc:" not in text


def test_a_message_without_headers_still_extracts_its_body() -> None:
    raw = b"Content-Type: text/plain; charset=utf-8\r\n\r\nbody only\r\n"
    text = eml_to_text(io.BytesIO(raw))
    assert "body only" in text
    assert not text.startswith("\n")


def test_the_body_is_still_extracted_alongside_the_headers() -> None:
    text = eml_to_text(_eml("From: A <a@example.com>\r\n"))
    assert "this is approved" in text


def test_an_html_only_message_keeps_its_body_once_an_envelope_is_added() -> None:
    """The ordering test for the interaction between two fixes in this PR.

    The HTML fallback fires on ``not text_content``. Prepending the envelope before that check
    makes an HTML-only message look like it already has a body, so its actual content is silently
    dropped and the document indexes as headers alone. Asserting on the body, not on the headers,
    is the point: the headers pass either way.
    """
    raw = (
        "From: Approver One <approver@example.com>\r\n"
        "Subject: Quarterly figures\r\n"
        "MIME-Version: 1.0\r\n"
        'Content-Type: text/html; charset="utf-8"\r\n'
        "\r\n"
        "<html><body><p>Total contract value is 12345.67.</p></body></html>\r\n"
    )
    text = eml_to_text(io.BytesIO(raw.encode()))

    assert "12345.67" in text, "HTML-only body was dropped once the envelope was prepended"
    assert "From: Approver One <approver@example.com>" in text
    assert text.index("From: Approver One") < text.index("12345.67")


def test_the_envelope_leads_the_document_even_when_an_attachment_is_extracted() -> None:
    """Attachments are appended, so the sender must still come first: an attachment's text can
    itself contain a quoted ``From:``, and whichever sender appears first is the one a reader and
    a model attribute the content to."""
    raw = (
        "From: Approver One <approver@example.com>\r\n"
        "Subject: With an attachment\r\n"
        "MIME-Version: 1.0\r\n"
        'Content-Type: multipart/mixed; boundary="b1"\r\n'
        "\r\n"
        "--b1\r\n"
        'Content-Type: text/plain; charset="utf-8"\r\n'
        "\r\n"
        "This is approved.\r\n"
        "--b1\r\n"
        'Content-Type: text/plain; charset="utf-8"\r\n'
        'Content-Disposition: attachment; filename="note.txt"\r\n'
        "\r\n"
        "From: Someone Else <other@example.com>\r\n"
        "--b1--\r\n"
    )
    text = eml_to_text(io.BytesIO(raw.encode()))

    assert text.index("From: Approver One") < text.index("Someone Else")
