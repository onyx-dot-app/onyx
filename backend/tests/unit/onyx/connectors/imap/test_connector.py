"""Unit tests for the IMAP connector's address, charset, and date handling.

Regression coverage for:
- https://github.com/onyx-dot-app/onyx/issues/7620: a display name containing a
  comma (e.g. `"Halvantzis, Savvas"`) used to be split on the comma, producing
  multiple bogus addresses and crashing the whole indexing run with a
  RuntimeError.
- A single malformed email (unparseable headers, etc.) used to raise out of
  `_load_from_checkpoint` and abort indexing for the rest of the mailbox.
- An unrecognized header charset label (e.g. the RFC 1428 `unknown-8bit`
  placeholder) used to raise `LookupError` out of header decoding.
"""

import email
from email.message import Message
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.connectors.imap.connector import _parse_addrs
from onyx.connectors.imap.connector import _parse_singular_addr
from onyx.connectors.imap.connector import ImapConnector
from onyx.connectors.imap.models import EmailHeaders
from onyx.connectors.models import Document
from tests.unit.onyx.connectors.utils import (
    load_everything_from_checkpoint_connector_from_checkpoint,
)

_DEFAULT_HEADERS = {
    "Subject": "Test Subject",
    "From": "sender@example.com",
    "To": "recipient@example.com",
    "Message-ID": "<default-id@example.com>",
    "Date": "Mon, 01 Jan 2024 10:00:00 +0000",
}


def _make_email_msg(
    overrides: dict[str, str] | None = None,
    omit: set[str] | None = None,
    body: str = "Hello world",
) -> Message:
    """Build a real `email.message.Message` from default + overridden headers."""
    headers = dict(_DEFAULT_HEADERS)
    headers.update(overrides or {})
    for key in omit or set():
        headers.pop(key, None)

    raw = "".join(f"{name}: {value}\r\n" for name, value in headers.items())
    raw += f"\r\n{body}\r\n"
    return email.message_from_string(raw)


# _parse_addrs / _parse_singular_addr (comma-in-quoted-name handling)


def test_parse_addrs_plain():
    assert _parse_addrs("john@example.com") == [("", "john@example.com")]


def test_parse_addrs_with_display_name():
    assert _parse_addrs("John Doe <john@example.com>") == [
        ("John Doe", "john@example.com")
    ]


def test_parse_addrs_empty_returns_empty_list():
    assert _parse_addrs("") == []


def test_parse_addrs_multiple_recipients():
    header = "John Doe <john@example.com>, jane@example.com"
    assert _parse_addrs(header) == [
        ("John Doe", "john@example.com"),
        ("", "jane@example.com"),
    ]


def test_parse_addrs_comma_in_quoted_display_name():
    # The bug: a comma inside a quoted display name must NOT split the address.
    header = '"Halvantzis, Savvas" <savvas@example.com>'
    assert _parse_addrs(header) == [("Halvantzis, Savvas", "savvas@example.com")]


def test_parse_addrs_multiple_with_commas_in_names():
    header = '"Halvantzis, Savvas" <savvas@example.com>, "Doe, John" <john@example.com>'
    assert _parse_addrs(header) == [
        ("Halvantzis, Savvas", "savvas@example.com"),
        ("Doe, John", "john@example.com"),
    ]


def test_parse_singular_addr_comma_in_quoted_name_does_not_raise():
    # Previously raised RuntimeError("Expected a singular address, but ...")
    # and aborted indexing for the whole mailbox.
    header = '"Halvantzis, Savvas" <savvas@example.com>'
    assert _parse_singular_addr(header) == ("Halvantzis, Savvas", "savvas@example.com")


def test_parse_singular_addr_multiple_returns_first_without_raising():
    header = "first@example.com, second@example.com"
    assert _parse_singular_addr(header) == ("", "first@example.com")


def test_parse_singular_addr_empty_raises():
    with pytest.raises(RuntimeError):
        _parse_singular_addr("")


# _load_from_checkpoint: one malformed email must not abort the whole mailbox


def test_load_from_checkpoint_skips_email_that_fails_to_parse():
    connector = ImapConnector(host="imap.example.com", mailboxes=["INBOX"])

    # Missing "From" fails `EmailHeaders` pydantic validation (sender is
    # required), which is exactly the kind of per-email failure Fix 2 guards.
    bad_msg = _make_email_msg(omit={"From"})
    good_msg = _make_email_msg({"Message-ID": "<good@example.com>"})

    with (
        patch.object(ImapConnector, "_get_mail_client", return_value=MagicMock()),
        patch("onyx.connectors.imap.connector._select_mailbox"),
        patch(
            "onyx.connectors.imap.connector._fetch_email_ids_in_mailbox",
            return_value=["1", "2"],
        ),
        patch(
            "onyx.connectors.imap.connector._fetch_email",
            side_effect=[bad_msg, good_msg],
        ),
    ):
        checkpoint = connector.build_dummy_checkpoint()
        outputs = load_everything_from_checkpoint_connector_from_checkpoint(
            connector=connector, start=0, end=1_000, checkpoint=checkpoint
        )

    documents = [
        item
        for output in outputs
        for item in output.items
        if isinstance(item, Document)
    ]

    # The bad email is skipped (logged, not raised); the good one still comes
    # through, and the checkpoint still runs to completion.
    assert len(documents) == 1
    assert documents[0].id == "<good@example.com>"
    assert outputs[-1].next_checkpoint.has_more is False


# EmailHeaders.from_email_msg: charset decoding (models._decode)


def test_from_email_msg_unknown_8bit_charset_does_not_crash():
    # "=?unknown-8bit?B?SGVsbG8=?=" is the RFC 2047 encoded form of "Hello"
    # tagged with the non-standard `unknown-8bit` charset label, which is not
    # a registered Python codec and used to raise LookupError.
    msg = _make_email_msg({"Subject": "=?unknown-8bit?B?SGVsbG8=?="})
    headers = EmailHeaders.from_email_msg(email_msg=msg)
    assert headers.subject == "Hello"
