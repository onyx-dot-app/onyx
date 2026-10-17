"""Tests for the two header-parsing failures reported against the IMAP connector.

Both of them ended an entire indexing run because of a single message:

- #15169: `_parse_addrs` split the raw header on commas, so a quoted display
  name like `"Lastname, Firstname" <user@example.com>` looked like two
  addresses and `_parse_singular_addr` raised.
- #15168: `Message-ID` is a SHOULD in RFC 5322, not a MUST. A message without
  one gave `EmailHeaders.id` a None and pydantic raised a ValidationError.
"""

import email
from email.message import Message

import pytest

from onyx.connectors.imap.connector import _parse_addrs, _parse_singular_addr
from onyx.connectors.imap.models import EmailHeaders


def _msg(
    from_: str = "Someone <someone@example.com>",
    subject: str = "A subject",
    to: str = "someone-else@example.com",
    date: str = "Tue, 1 Sep 2026 10:00:00 +0000",
    message_id: str | None = "<abc123@example.com>",
    body: str = "hello",
) -> Message:
    headers = [f"From: {from_}", f"Subject: {subject}", f"To: {to}", f"Date: {date}"]
    if message_id is not None:
        headers.append(f"Message-ID: {message_id}")
    return email.message_from_string("\n".join(headers) + f"\n\n{body}\n")


# --- #15169: quoted display names ------------------------------------------


def test_quoted_display_name_with_comma_is_one_address() -> None:
    name, addr = _parse_singular_addr(
        raw_header='"Lastname, Firstname" <user@example.com>'
    )

    assert addr == "user@example.com"
    assert name == "Lastname, Firstname"


def test_several_real_addresses_still_parse_separately() -> None:
    parsed = _parse_addrs(
        raw_header='"Lastname, Firstname" <a@example.com>, Plain Name <b@example.com>'
    )

    assert [addr for _name, addr in parsed] == ["a@example.com", "b@example.com"]


def test_unquoted_single_address_is_unchanged() -> None:
    assert _parse_addrs(raw_header="plain@example.com") == [("", "plain@example.com")]


# --- #15168: missing Message-ID --------------------------------------------


def test_missing_message_id_does_not_raise() -> None:
    headers = EmailHeaders.from_email_msg(email_msg=_msg(message_id=None))

    assert headers.id
    assert headers.subject == "A subject"


def test_synthesized_id_is_stable_across_runs() -> None:
    # The id becomes the Document id. If it changed between runs, every index
    # would file the same email again as a new document.
    first = EmailHeaders.from_email_msg(email_msg=_msg(message_id=None))
    second = EmailHeaders.from_email_msg(email_msg=_msg(message_id=None))

    assert first.id == second.id


@pytest.mark.parametrize(
    "changed",
    [
        {"subject": "A different subject"},
        {"from_": "Someone Else <other@example.com>"},
        {"body": "different body"},
        {"date": "Wed, 2 Sep 2026 10:00:00 +0000"},
    ],
)
def test_different_messages_get_different_ids(changed: dict[str, str]) -> None:
    base = EmailHeaders.from_email_msg(email_msg=_msg(message_id=None))
    other = EmailHeaders.from_email_msg(email_msg=_msg(message_id=None, **changed))

    assert base.id != other.id


def test_a_present_message_id_is_still_used() -> None:
    headers = EmailHeaders.from_email_msg(
        email_msg=_msg(message_id="<real-id@example.com>")
    )

    assert headers.id == "<real-id@example.com>"
