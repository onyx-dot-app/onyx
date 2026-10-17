import email

from onyx.connectors.imap.models import EmailHeaders


def _msg(raw: bytes) -> email.message.Message:
    return email.message_from_bytes(raw)


def test_multi_segment_from_header_keeps_address() -> None:
    # Encoded-word display name followed by a plain-text <addr> tail:
    # decode_header returns two segments; only the first was used, so the
    # address was silently dropped before parsing.
    msg = _msg(
        b"From: =?UTF-8?Q?FabLab_M=C3=BCnchen_Recommended_U?=\r\n"
        b" =?UTF-8?Q?pdates_=28Confluence=29?= <wiki@fablab-muenchen.de>\r\n"
        b"Message-ID: <1@example.com>\r\n"
        b"Date: Mon, 1 Jan 2024 10:00:00 +0000\r\n"
        b"\r\nbody\r\n"
    )
    headers = EmailHeaders.from_email_msg(msg)
    assert headers.sender == (
        "FabLab München Recommended Updates (Confluence) "
        "<wiki@fablab-muenchen.de>"
    )


def test_encoded_word_inside_quotes_preserves_addr() -> None:
    # '=?UTF-8?B?RlJJVFohQm94IDc1OTA=?=' = 'FRITZ!Box 7590'; encoded words
    # inside quotes are literal per RFC 2047 but the <addr> tail must survive.
    msg = _msg(
        b'From: "=?UTF-8?B?RlJJVFohQm94IDc1OTA=?=" <noreply@example.com>\r\n'
        b"Message-ID: <2@example.com>\r\n"
        b"Date: Mon, 1 Jan 2024 10:00:00 +0000\r\n"
        b"\r\nbody\r\n"
    )
    headers = EmailHeaders.from_email_msg(msg)
    assert "noreply@example.com" in headers.sender
