"""Unit tests for the IMAP connector's address, charset, and date handling.

Regression coverage for:
- https://github.com/onyx-dot-app/onyx/issues/7620: a display name containing a
  comma (e.g. `"Halvantzis, Savvas"`) used to be split on the comma, producing
  multiple bogus addresses and crashing the whole indexing run with a
  RuntimeError.
"""

import pytest

from onyx.connectors.imap.connector import _parse_addrs
from onyx.connectors.imap.connector import _parse_singular_addr

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
