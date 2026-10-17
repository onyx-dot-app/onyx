"""The HubSpot checks' rows: the design's short lines and descriptions, the
run order, the form-run sign-in policy, the rate-limit stop, Error Details,
and what a check that tested nothing says."""

from collections.abc import Callable
from unittest.mock import MagicMock

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CheckErrorKind,
    CheckNotRunReason,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import (
    RateLimitTriedTooManyTimesError,
)
from onyx.connectors.hubspot.capability_checks import (
    build_hubspot_doc_permission_sync_checks,
    build_hubspot_indexing_checks,
)
from onyx.connectors.hubspot.config import HubSpotObjectType
from onyx.connectors.hubspot.models import HubSpotPage, HubSpotRecord, HubSpotUser
from onyx.connectors.hubspot.source_operations import (
    HubSpotApiError,
    HubSpotConnectionError,
)
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.db.enums import AccessType
from tests.unit.onyx.connectors.hubspot.test_hubspot_capability_checks import (
    _gateway,
    _record,
    _refusal,
)

_ALL_CHECKS: list[CapabilityCheck] = (
    build_hubspot_indexing_checks() + build_hubspot_doc_permission_sync_checks()
)
_READ_TICKETS = "hubspot_tickets_readable"


def _run_all(
    check_ids: list[str],
    gateway: MagicMock,
    object_types: list[str] | None = None,
    *,
    form_run: bool = False,
) -> dict[str, CapabilityCheckResult]:
    checks: list[CapabilityCheck] = [
        check for check in _ALL_CHECKS if check.check_id in check_ids
    ]
    context = CapabilityCheckContext(
        source=DocumentSource.HUBSPOT,
        credential_json={"hubspot_access_token": "pat-na1-secret"},
        connector_specific_config=(
            None if object_types is None else {"object_types": object_types}
        ),
        access_type=AccessType.SYNC,
        source_operations=gateway,
    )
    return {
        result.check_id: result
        for result in run_capability_checks(checks, context, form_run=form_run)
    }


def _run(
    check_id: str,
    gateway: MagicMock,
    object_types: list[str] | None = None,
    *,
    form_run: bool = False,
) -> CapabilityCheckResult:
    return _run_all([check_id], gateway, object_types, form_run=form_run)[check_id]


def _records_only_in(
    *object_types: HubSpotObjectType,
) -> Callable[..., HubSpotPage[HubSpotRecord]]:
    """A list_records side effect: one record of each given type, none of
    the others."""

    def list_records(
        variant: HubSpotObjectType, **_: object
    ) -> HubSpotPage[HubSpotRecord]:
        return HubSpotPage(items=[_record("1")] if variant in object_types else [])

    return list_records


# --- Sign in to HubSpot ---


def test_sign_in_names_the_account() -> None:
    result = _run("hubspot_token", _gateway())

    assert result.display_name == "Sign in to HubSpot"
    assert result.status == CapabilityCheckStatus.PASSED
    assert result.summary == "Signed in to account 46399533"


def test_a_rejected_token_says_so() -> None:
    gateway = _gateway()
    gateway.get_portal_id.side_effect = _refusal("portal info", 401)

    result = _run("hubspot_token", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.error_kind == CheckErrorKind.REJECTED
    assert result.summary == "HubSpot rejected the API token"


def test_a_denied_sign_in_says_the_token_cannot_read_the_account() -> None:
    gateway = _gateway()
    gateway.get_portal_id.side_effect = _refusal("portal info", 403)

    result = _run("hubspot_token", gateway)

    assert result.error_kind == CheckErrorKind.PERMISSION
    assert result.summary == "Token cannot read the account"


def test_a_missing_token_says_so() -> None:
    gateway = _gateway()
    gateway.get_portal_id.side_effect = ConnectorMissingCredentialError("HubSpot")

    result = _run("hubspot_token", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == "Account has no API token"


def test_an_unreachable_hubspot_fails_only_a_form_run() -> None:
    gateway = _gateway()
    gateway.get_portal_id.side_effect = HubSpotConnectionError(
        "portal info", timed_out=False, detail="refused"
    )

    form = _run("hubspot_token", gateway, form_run=True)
    stored = _run("hubspot_token", gateway)

    assert form.status == CapabilityCheckStatus.FAILED
    assert stored.status == CapabilityCheckStatus.INCOMPLETE
    assert form.summary == stored.summary == "Cannot reach HubSpot"


def test_a_sign_in_timeout_fails_only_a_form_run() -> None:
    gateway = _gateway()
    gateway.get_portal_id.side_effect = HubSpotConnectionError(
        "portal info", timed_out=True, detail="read timed out"
    )

    form = _run("hubspot_token", gateway, form_run=True)
    stored = _run("hubspot_token", gateway)

    assert form.status == CapabilityCheckStatus.FAILED
    assert stored.status == CapabilityCheckStatus.INCOMPLETE
    assert form.summary == "Sign-in timed out"


def test_an_api_error_carries_the_request_and_body() -> None:
    gateway = _gateway()
    gateway.get_portal_id.side_effect = HubSpotApiError(
        "portal info",
        500,
        None,
        '{"status": "error"}',
        method="GET",
        url="https://api.hubapi.com/integrations/v1/me",
    )

    result = _run("hubspot_token", gateway)

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.summary == "Unexpected response from HubSpot"
    assert result.error_detail is not None
    assert result.error_detail.status_code == 500
    assert result.error_detail.request == "GET api.hubapi.com/integrations/v1/me"
    assert result.error_detail.response_excerpt == '{"status": "error"}'


def test_a_rate_limit_is_incomplete_and_stops_the_run() -> None:
    gateway = _gateway()
    gateway.list_records.side_effect = RateLimitTriedTooManyTimesError("429")

    results = _run_all(
        ["hubspot_token", _READ_TICKETS, "hubspot_companies_readable"], gateway
    )

    tickets = results[_READ_TICKETS]
    assert tickets.status == CapabilityCheckStatus.INCOMPLETE
    assert tickets.error_kind == CheckErrorKind.RATE_LIMITED
    assert tickets.summary == "Rate limited by HubSpot"
    assert (
        results["hubspot_companies_readable"].not_run_reason
        == CheckNotRunReason.RATE_LIMITED
    )


def test_a_failed_sign_in_stops_the_checks_after_it() -> None:
    gateway = _gateway()
    gateway.get_portal_id.side_effect = _refusal("portal info", 401)

    results = _run_all(
        [
            "hubspot_token",
            _READ_TICKETS,
            "hubspot_associations",
            "hubspot_notes",
            "hubspot_users",
            "hubspot_record_viewers",
        ],
        gateway,
    )

    for check_id in (
        _READ_TICKETS,
        "hubspot_associations",
        "hubspot_notes",
        "hubspot_users",
        "hubspot_record_viewers",
    ):
        assert results[check_id].status == CapabilityCheckStatus.SKIPPED
        assert results[check_id].blocked_by == "hubspot_token"
    gateway.list_records.assert_not_called()


# --- Read {type} ---


def test_a_read_check_counts_the_records() -> None:
    gateway = _gateway()
    gateway.search_records.return_value = HubSpotPage(items=[_record("1")], total=3)

    result = _run(_READ_TICKETS, gateway)

    assert result.display_name == "Read tickets"
    assert result.summary == "Found 3 tickets"


def test_a_read_check_counts_one_record_in_the_singular() -> None:
    gateway = _gateway()
    gateway.search_records.return_value = HubSpotPage(items=[_record("1")], total=1)

    assert _run("hubspot_companies_readable", gateway).summary == "Found 1 company"


def test_a_denied_read_names_the_scope() -> None:
    gateway = _gateway()
    gateway.list_records.side_effect = _refusal("deals listing", 403)

    result = _run("hubspot_deals_readable", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == "Token cannot read deals"
    assert result.description is not None
    assert result.description.endswith(
        "In HubSpot, add `crm.objects.deals.read` to the private app's scopes."
    )


def test_an_empty_type_is_skipped_when_another_has_records() -> None:
    gateway = _gateway()
    gateway.list_records.side_effect = _records_only_in(HubSpotObjectType.CONTACTS)

    result = _run(_READ_TICKETS, gateway)

    assert result.status == CapabilityCheckStatus.SKIPPED
    assert result.not_run_reason == CheckNotRunReason.NOTHING_IN_SCOPE
    assert result.summary == "No tickets in HubSpot"


def test_no_record_of_any_selected_type_fails_the_first_read() -> None:
    gateway = _gateway()
    gateway.list_records.return_value = HubSpotPage(items=[])

    results = _run_all(
        [_READ_TICKETS, "hubspot_companies_readable"],
        gateway,
        object_types=["companies", "tickets"],
    )

    first = results[_READ_TICKETS]
    assert first.status == CapabilityCheckStatus.FAILED
    assert first.summary == "No records in the selected types"
    assert results["hubspot_companies_readable"].status == CapabilityCheckStatus.SKIPPED


# --- List linked records and Sample notes ---


def test_linked_records_name_the_types() -> None:
    result = _run("hubspot_associations", _gateway())

    assert result.display_name == "List linked records"
    assert result.summary == "Listed contacts linked to tickets"


def test_linked_records_run_past_an_empty_type() -> None:
    gateway = _gateway()
    gateway.list_records.side_effect = _records_only_in(HubSpotObjectType.CONTACTS)

    results = _run_all(
        ["hubspot_token", _READ_TICKETS, "hubspot_associations"], gateway
    )

    assert results[_READ_TICKETS].status == CapabilityCheckStatus.SKIPPED
    associations = results["hubspot_associations"]
    assert associations.status == CapabilityCheckStatus.PASSED
    assert associations.summary == "Listed companies linked to contacts"


def test_a_denied_link_names_the_linked_type_and_scope() -> None:
    gateway = _gateway()
    gateway.list_associations.side_effect = _refusal("associations", 403)

    result = _run("hubspot_associations", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == "Cannot read linked contacts"
    assert result.description is not None
    assert "`crm.objects.contacts.read`" in result.description


def test_no_record_in_scope_skips_the_samples() -> None:
    gateway = _gateway()
    gateway.list_records.return_value = HubSpotPage(items=[])

    results = _run_all(
        ["hubspot_associations", "hubspot_notes", "hubspot_record_viewers"], gateway
    )

    for result in results.values():
        assert result.status == CapabilityCheckStatus.SKIPPED
        assert result.not_run_reason == CheckNotRunReason.NOTHING_IN_SCOPE
        assert result.summary == "No records in scope"


def test_notes_name_the_record_type() -> None:
    result = _run("hubspot_notes", _gateway())

    assert result.display_name == "Sample notes"
    assert result.summary == "Read a note linked to a ticket"


def test_a_record_without_notes_is_incomplete() -> None:
    gateway = _gateway()
    gateway.list_associations.return_value = HubSpotPage(items=[])

    result = _run("hubspot_notes", gateway)

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.summary == "No notes found to test"


def test_denied_notes_say_so() -> None:
    gateway = _gateway()
    gateway.read_records.side_effect = _refusal("notes batch read", 403)

    assert _run("hubspot_notes", gateway).summary == "Token cannot read notes"


# --- List users and Read record viewers ---


def test_users_are_counted() -> None:
    result = _run("hubspot_users", _gateway())

    assert result.display_name == "List users"
    assert result.summary == "1 user found"


def test_a_full_page_of_users_is_a_lower_bound() -> None:
    gateway = _gateway()
    gateway.list_users.return_value = HubSpotPage(
        items=[HubSpotUser(id=i) for i in range(100)], next_after="100"
    )

    assert _run("hubspot_users", gateway).summary == "100+ users found"


def test_denied_users_name_the_scope() -> None:
    gateway = _gateway()
    gateway.list_users.side_effect = _refusal("user listing", 403)

    result = _run("hubspot_users", gateway)

    assert result.summary == "Token cannot list users"
    assert result.description is not None
    assert "`settings.users.read`" in result.description


def test_viewers_are_counted_on_a_sample_record() -> None:
    gateway = _gateway()
    gateway.get_record_viewers.return_value = {"1": {7, 8}}

    result = _run("hubspot_record_viewers", gateway)

    assert result.display_name == "Read record viewers"
    assert result.summary == "2 users can view a sample ticket"


def test_a_denied_sample_listing_fails_the_viewers_check() -> None:
    gateway = _gateway()
    gateway.list_records.side_effect = _refusal("tickets listing", 403)

    result = _run("hubspot_record_viewers", gateway)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == "Token cannot read tickets"
    assert result.description is not None
    assert result.description.startswith("Permission sync cannot sync tickets.")


def test_denied_viewers_say_so() -> None:
    gateway = _gateway()
    gateway.get_record_viewers.side_effect = _refusal("record viewers", 403)

    result = _run("hubspot_record_viewers", gateway)

    assert result.summary == "Token cannot read record viewers"


def test_failed_users_stop_the_viewers_check() -> None:
    gateway = _gateway()
    gateway.list_users.side_effect = _refusal("user listing", 403)

    results = _run_all(["hubspot_users", "hubspot_record_viewers"], gateway)

    viewers = results["hubspot_record_viewers"]
    assert viewers.status == CapabilityCheckStatus.SKIPPED
    assert viewers.not_run_reason == CheckNotRunReason.DEPENDENCY_FAILED
    assert viewers.blocked_by == "hubspot_users"
    gateway.get_record_viewers.assert_not_called()
