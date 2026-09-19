"""Tests for the IMAP connector's address-parsing resilience (#7620).

The connector previously raised ``RuntimeError`` on malformed or multi-address
sender headers, which killed the entire indexing run on a single bad email.
"""

from __future__ import annotations

import email
import logging
from datetime import datetime
from datetime import timezone

import pytest

from onyx.connectors.imap.connector import _convert_email_headers_and_body_into_document
from onyx.connectors.imap.connector import _parse_addrs
from onyx.connectors.imap.connector import _parse_singular_addr
from onyx.connectors.imap.models import EmailHeaders


def _headers(sender: str, recipients: str | None = None) -> EmailHeaders:
    return EmailHeaders(
        id="<msg-1@example.com>",
        subject="Subject",
        sender=sender,
        recipients=recipients,
        date=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _message(body: str = "hello") -> email.message.Message:
    msg = email.message.Message()
    msg.set_payload(body)
    msg.set_charset("utf-8")
    return msg


# ---- _parse_singular_addr ----


def test_parse_singular_addr_valid_single() -> None:
    assert _parse_singular_addr("Alice <alice@example.com>") == (
        "Alice",
        "alice@example.com",
    )


def test_parse_singular_addr_bare_quote_returns_none() -> None:
    # Literal reporter case from #7620 — the trace shows raw_header='"'.
    assert _parse_singular_addr('"') is None


def test_parse_singular_addr_empty_string_returns_none() -> None:
    assert _parse_singular_addr("") is None


def test_parse_singular_addr_whitespace_returns_none() -> None:
    assert _parse_singular_addr("   ") is None


def test_parse_singular_addr_multiple_uses_first_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="onyx.connectors.imap.connector")
    result = _parse_singular_addr("alice@example.com, bob@example.com")
    assert result == ("", "alice@example.com")
    assert any(
        "singular address header but found 2" in r.getMessage() for r in caplog.records
    )


def test_parse_singular_addr_quoted_display_name_with_comma() -> None:
    # Valid RFC 5322 address with a comma inside the quoted display name.
    # Naive comma-splitting would wrongly treat this as two addresses;
    # getaddresses correctly parses it as one.
    assert _parse_singular_addr('"Doe, John" <john@example.com>') == (
        "Doe, John",
        "john@example.com",
    )


def test_parse_addrs_quoted_display_name_with_comma_is_single_entry() -> None:
    assert _parse_addrs('"Doe, John" <john@example.com>') == [
        ("Doe, John", "john@example.com")
    ]


def test_parse_addrs_multiple_mixed_with_quoted_commas() -> None:
    result = _parse_addrs('"Doe, John" <john@example.com>, alice@example.com')
    assert result == [
        ("Doe, John", "john@example.com"),
        ("", "alice@example.com"),
    ]


def test_parse_singular_addr_malformed_and_one_valid() -> None:
    # Garbage plus one recoverable address — returns the recoverable one.
    result = _parse_singular_addr("not-an-address, bob@example.com")
    assert result is not None
    _name, addr = result
    assert addr in {"bob@example.com", "not-an-address"}
    # email.utils.parseaddr is surprisingly permissive; the key assertion is
    # that at least one parse succeeds and we don't raise.


# ---- _convert_email_headers_and_body_into_document ----


def test_converter_skips_attribution_when_sender_unparseable() -> None:
    doc = _convert_email_headers_and_body_into_document(
        email_msg=_message(),
        email_headers=_headers(sender='"', recipients=None),
        include_perm_sync=False,
    )
    assert doc.primary_owners == []


def test_converter_still_attributes_recipients_when_sender_fails() -> None:
    doc = _convert_email_headers_and_body_into_document(
        email_msg=_message(),
        email_headers=_headers(sender='"', recipients="Bob <bob@example.com>"),
        include_perm_sync=False,
    )
    assert doc.primary_owners is not None
    emails = {owner.email for owner in doc.primary_owners}
    assert emails == {"bob@example.com"}


def test_converter_regression_from_issue_7620() -> None:
    """Direct regression: the trace from #7620 must not raise."""
    doc = _convert_email_headers_and_body_into_document(
        email_msg=_message(),
        email_headers=_headers(sender='"'),
        include_perm_sync=False,
    )
    assert doc.id == "<msg-1@example.com>"
