"""The Outlook checks' rows: the design's names, short lines and
descriptions, the run order, the partial finds of selected mailboxes and
groups, and what a check that tested nothing says."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.connectors.capability_checks.models import (
    MAX_FINDING_OPTIONS,
    CapabilityCheck,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CheckErrorKind,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.microsoft_utils.entra import EntraGroup
from onyx.connectors.microsoft_utils.graph_errors import MicrosoftGraphError
from onyx.connectors.outlook.capability_checks import build_outlook_indexing_checks
from onyx.connectors.outlook.models import OutlookEventPage, OutlookMailboxPage
from tests.unit.onyx.connectors.outlook.outlook_api_shapes import (
    MAILBOX_ADDRESS,
    event,
    graph_error,
    mailbox,
    message,
)
from tests.unit.onyx.connectors.outlook.test_outlook_capability_checks import (
    _context,
    _gateway,
)

_CHECKS: dict[str, CapabilityCheck] = {
    check.check_id: check for check in build_outlook_indexing_checks()
}


def _healthy() -> MagicMock:
    gateway: MagicMock = _gateway()
    gateway.resolve_groups.return_value = [EntraGroup(id="g", displayName="Sales")]
    gateway.fetch_calendar_delta_page.return_value = OutlookEventPage(events=[])
    gateway.read_any_event.return_value = event()
    return gateway


def _run_all(
    check_ids: list[str], gateway: MagicMock, config: dict[str, Any] | None = None
) -> dict[str, CapabilityCheckResult]:
    return {
        result.check_id: result
        for result in run_capability_checks(
            [_CHECKS[check_id] for check_id in check_ids],
            _context(gateway, config if config is not None else {}),
        )
    }


def _run(
    check_id: str, gateway: MagicMock, config: dict[str, Any] | None = None
) -> CapabilityCheckResult:
    return _run_all([check_id], gateway, config)[check_id]


def test_the_rows_have_the_design_names() -> None:
    assert {check_id: check.display_name for check_id, check in _CHECKS.items()} == {
        "outlook_token_auth": "Sign in to Microsoft",
        "outlook_mailbox_listing": "List mailboxes",
        "outlook_mailbox_count": "List mailboxes",
        "outlook_configured_mailboxes": "Find selected mailboxes",
        "outlook_configured_groups": "Find selected groups",
        "outlook_mail_read": "Sample mail",
        "outlook_calendar_read": "Sample calendars",
    }
    assert _CHECKS["outlook_mailbox_count"].row_id == "outlook_mailbox_listing"
    assert _CHECKS["outlook_mailbox_listing"].validates_binding


@pytest.mark.parametrize(
    ("check_id", "config", "summary"),
    [
        ("outlook_token_auth", {}, "Signed in as Onyx"),
        ("outlook_mailbox_listing", {}, "Tenant user list is readable"),
        ("outlook_mailbox_count", {}, "Up to 1 mailbox"),
        (
            "outlook_configured_mailboxes",
            {"mailboxes": [MAILBOX_ADDRESS]},
            "1 selected mailbox open",
        ),
        (
            "outlook_configured_groups",
            {"mailbox_groups": ["Sales"]},
            "1 selected group found",
        ),
        (
            "outlook_mail_read",
            {"mailboxes": [MAILBOX_ADDRESS]},
            f"Read mail in {MAILBOX_ADDRESS}",
        ),
        ("outlook_mail_read", {}, "Read mail in a sampled mailbox"),
        (
            "outlook_calendar_read",
            {"include_calendar": True},
            "Read an event in a sampled mailbox",
        ),
    ],
)
def test_a_passing_check_says_what_it_found(
    check_id: str, config: dict[str, Any], summary: str
) -> None:
    result = _run(check_id, _healthy(), config)

    assert result.status == CapabilityCheckStatus.PASSED, result.message
    assert result.summary == summary


def test_a_sample_without_attachments_passes_with_a_caveat() -> None:
    result = _run("outlook_mail_read", _healthy())

    assert result.advisories
    assert "attachment" in result.advisories[0].message


def test_a_refused_user_listing_names_the_grant_and_stops_the_samples() -> None:
    gateway = _healthy()
    gateway.list_mailbox_users.side_effect = graph_error(403)

    results = _run_all(
        ["outlook_mailbox_listing", "outlook_mail_read", "outlook_calendar_read"],
        gateway,
        {"include_calendar": True},
    )

    listing = results["outlook_mailbox_listing"]
    assert listing.status == CapabilityCheckStatus.FAILED
    assert listing.summary == "No permission to read user directory"
    for check_id in ("outlook_mail_read", "outlook_calendar_read"):
        assert results[check_id].blocked_by == "outlook_mailbox_listing"


# --- Find selected mailboxes and groups ---


def test_one_missing_mailbox_of_two_is_a_partial_find() -> None:
    gateway = _healthy()
    gateway.resolve_mailbox.side_effect = lambda address: (
        None if address == "ghost@contoso.com" else mailbox()
    )
    config: dict[str, Any] = {"mailboxes": ["ghost@contoso.com", MAILBOX_ADDRESS]}

    results = _run_all(
        ["outlook_configured_mailboxes", "outlook_mail_read"], gateway, config
    )

    found = results["outlook_configured_mailboxes"]
    assert found.status == CapabilityCheckStatus.INCOMPLETE
    assert found.partial
    assert found.summary == "Mailbox not found: ghost@contoso.com"
    # The sample opens the mailbox that answers.
    assert results["outlook_mail_read"].summary == f"Read mail in {MAILBOX_ADDRESS}"


def test_a_partial_find_gives_the_full_address_and_reason() -> None:
    long_address = "shared-mailbox-for-the-finance-team@contoso.com"
    gateway = _healthy()
    gateway.resolve_mailbox.side_effect = lambda address: (
        None if address == long_address else mailbox()
    )

    result = _run(
        "outlook_configured_mailboxes",
        gateway,
        {"mailboxes": [long_address, MAILBOX_ADDRESS]},
    )

    assert result.partial
    assert result.summary is not None and len(result.summary) <= 40
    assert result.description is not None
    assert result.description.startswith(
        f"Not reachable: {long_address} (no such user)."
    )
    assert len(result.description.splitlines()) <= 3


def test_a_capped_mailbox_count_is_a_lower_bound() -> None:
    gateway = _healthy()
    gateway.list_mailbox_users.return_value = OutlookMailboxPage(
        mailboxes=[mailbox()] * (MAX_FINDING_OPTIONS + 1)
    )

    result = _run("outlook_mailbox_count", gateway)

    assert result.summary == f"At least {MAX_FINDING_OPTIONS} mailboxes"


def test_no_selected_mailbox_found_fails() -> None:
    gateway = _healthy()
    gateway.resolve_mailbox.return_value = None

    result = _run(
        "outlook_configured_mailboxes",
        gateway,
        {"mailboxes": ["a@contoso.com", "b@contoso.com"]},
    )

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == "No selected mailbox found"


def test_a_group_that_matches_nothing_names_it() -> None:
    gateway = _healthy()
    gateway.resolve_groups.return_value = []

    result = _run("outlook_configured_groups", gateway, {"mailbox_groups": ["Ghost"]})

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == "Group not found: Ghost"


def test_a_refused_group_read_names_the_grant() -> None:
    gateway = _healthy()
    gateway.resolve_groups.side_effect = graph_error(403)

    result = _run("outlook_configured_groups", gateway, {"mailbox_groups": ["Sales"]})

    assert result.summary == "No permission to read Entra groups"


# --- Samples ---


def test_an_empty_mailbox_is_incomplete() -> None:
    gateway = _healthy()
    gateway.read_any_message.return_value = None

    result = _run("outlook_mail_read", gateway, {"mailboxes": [MAILBOX_ADDRESS]})

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.summary == f"No mail found in {MAILBOX_ADDRESS}"


def test_a_denied_body_read_says_bodies_are_not_readable() -> None:
    gateway = _healthy()
    gateway.read_any_message.side_effect = graph_error(403)

    result = _run("outlook_mail_read", gateway, {"mailboxes": [MAILBOX_ADDRESS]})

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == "Mail bodies are not readable"


def test_empty_pages_are_incomplete() -> None:
    gateway = _healthy()
    gateway.read_any_message.side_effect = MicrosoftGraphError(
        None, "EmptyPages", "20 empty pages"
    )

    result = _run("outlook_mail_read", gateway, {"mailboxes": [MAILBOX_ADDRESS]})

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.summary == "Message listing did not finish"


def test_a_withheld_event_body_says_details_are_not_readable() -> None:
    gateway = _healthy()
    gateway.read_any_event.return_value = event(body_present=False)

    result = _run("outlook_calendar_read", gateway, {"include_calendar": True})

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == "Event details are not readable"


def test_no_event_anywhere_is_incomplete() -> None:
    gateway = _healthy()
    gateway.read_any_event.return_value = None

    result = _run("outlook_calendar_read", gateway, {"include_calendar": True})

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.summary == "No events found to test"


def test_a_mailbox_with_messages_reads_them() -> None:
    gateway = _healthy()
    gateway.read_any_message.return_value = message(has_attachments=True)

    result = _run("outlook_mail_read", gateway)

    assert result.status == CapabilityCheckStatus.PASSED
    assert not result.advisories
    gateway.list_message_attachments.assert_called_once()


def test_a_throttled_listing_is_rate_limited() -> None:
    gateway = _healthy()
    gateway.list_mailbox_users.side_effect = graph_error(429, "TooManyRequests")

    result = _run("outlook_mailbox_listing", gateway)

    assert result.error_kind == CheckErrorKind.RATE_LIMITED
    assert result.summary == "Microsoft is throttling requests"
