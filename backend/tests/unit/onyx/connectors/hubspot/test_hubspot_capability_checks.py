"""Behavior tests for the HubSpot capability checks.

Each check runs against an autospecced HubSpotSourceOperations. The coverage
harness enforces that some check reaches every gateway operation, so these
tests pin registration, verdicts, and the error type and scope hint an admin
sees on a refusal.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, create_autospec

import pytest

from ee.onyx.connectors.perm_sync_valid import validate_perm_sync
from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheckContext,
    CapabilityCheckStatus,
    CapabilityVerdict,
    CredentialCapability,
    compute_capability_verdicts,
)
from onyx.connectors.capability_checks.registry import get_capability_checks
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.exceptions import (
    CredentialInvalidError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.hubspot.capability_checks import (
    build_hubspot_doc_permission_sync_checks,
    build_hubspot_indexing_checks,
)
from onyx.connectors.hubspot.config import HubSpotObjectType
from onyx.connectors.hubspot.connector import HubSpotConnector
from onyx.connectors.hubspot.models import HubSpotPage, HubSpotRecord, HubSpotUser
from onyx.connectors.hubspot.source_operations import (
    HubSpotApiError,
    HubSpotSourceOperations,
)
from onyx.db.enums import AccessType

MOMENT = datetime(2024, 6, 6, tzinfo=timezone.utc)
_CHECKS_BY_ID = {
    check.check_id: check
    for check in build_hubspot_indexing_checks()
    + build_hubspot_doc_permission_sync_checks()
}


def _record(record_id: str) -> HubSpotRecord:
    return HubSpotRecord(id=record_id, created_at=MOMENT, updated_at=MOMENT)


def _refusal(operation: str, status: int) -> HubSpotApiError:
    return HubSpotApiError(operation, status, None, "")


def _gateway() -> MagicMock:
    """A healthy portal with one record of each type, one note and one user."""
    gateway = create_autospec(HubSpotSourceOperations, instance=True)
    gateway.get_portal_id.return_value = "46399533"
    gateway.list_records.return_value = HubSpotPage(items=[_record("1")])
    gateway.search_records.return_value = HubSpotPage(items=[_record("1")])
    gateway.read_records.return_value = [_record("1")]
    gateway.list_associations.return_value = HubSpotPage(items=["9"])
    gateway.list_users.return_value = HubSpotPage(items=[HubSpotUser(id=7)])
    gateway.get_user.return_value = HubSpotUser(id=7, email="ada@example.com")
    gateway.get_record_viewers.return_value = {"1": {7}}
    return gateway


def _context(
    gateway: MagicMock, object_types: list[str] | None = None
) -> CapabilityCheckContext:
    return CapabilityCheckContext(
        source=DocumentSource.HUBSPOT,
        credential_json={"hubspot_access_token": "token"},
        connector_specific_config=(
            None if object_types is None else {"object_types": object_types}
        ),
        access_type=AccessType.SYNC,
        source_operations=gateway,
    )


def _run(check_id: str, context: CapabilityCheckContext) -> None:
    _CHECKS_BY_ID[check_id].run(context)


@pytest.mark.usefixtures("enable_ee")
def test_named_checks_replace_both_fallbacks() -> None:
    check_ids = {
        check.check_id for check in get_capability_checks(DocumentSource.HUBSPOT)
    }

    assert "hubspot_connector_settings" not in check_ids
    assert "hubspot_perm_sync" not in check_ids
    assert set(_CHECKS_BY_ID) <= check_ids


@pytest.mark.usefixtures("enable_ee")
def test_a_healthy_portal_passes_every_capability() -> None:
    results = run_capability_checks(
        get_capability_checks(DocumentSource.HUBSPOT), _context(_gateway())
    )

    assert {r.check_id: r.status for r in results} == dict.fromkeys(
        _CHECKS_BY_ID, CapabilityCheckStatus.PASSED
    )
    verdicts = compute_capability_verdicts(
        {CredentialCapability.INDEXING, CredentialCapability.DOC_PERMISSION_SYNC},
        results,
    )
    assert verdicts[CredentialCapability.INDEXING] == CapabilityVerdict.PASSED
    assert (
        verdicts[CredentialCapability.DOC_PERMISSION_SYNC] == CapabilityVerdict.PASSED
    )


def test_a_rejected_token_is_an_invalid_credential() -> None:
    gateway = _gateway()
    gateway.get_portal_id.side_effect = _refusal("portal info", 401)

    with pytest.raises(CredentialInvalidError):
        _run("hubspot_token", _context(gateway))


@pytest.mark.parametrize(
    "object_type, scope",
    [
        (HubSpotObjectType.TICKETS, "`tickets`"),
        (HubSpotObjectType.DEALS, "`crm.objects.deals.read`"),
    ],
)
def test_a_missing_read_scope_names_the_scope(
    object_type: HubSpotObjectType, scope: str
) -> None:
    gateway = _gateway()
    gateway.list_records.side_effect = _refusal(f"{object_type} listing", 403)

    with pytest.raises(InsufficientPermissionsError, match=scope):
        _run(f"hubspot_{object_type.value}_readable", _context(gateway))


@pytest.mark.parametrize(
    "object_types, applies",
    [(["deals"], {"deals"}), ([], set())],
    ids=["deals-only", "none"],
)
def test_a_read_check_applies_only_to_configured_types(
    object_types: list[str], applies: set[str]
) -> None:
    context = _context(_gateway(), object_types=object_types)
    assert context.form_state is not None

    applying = {
        object_type.value
        for object_type in HubSpotObjectType
        if _CHECKS_BY_ID[f"hubspot_{object_type.value}_readable"].applies(
            context.form_state
        )
    }

    assert applying == applies


def test_an_optional_check_reports_a_refused_listing_as_indeterminate() -> None:
    """The read check already fails for the refused type, so the associations
    check adds no second failed row."""
    gateway = _gateway()
    gateway.list_records.side_effect = _refusal("tickets listing", 403)

    with pytest.raises(UnexpectedValidationError, match="No record to probe"):
        _run("hubspot_associations", _context(gateway))


def test_a_missing_users_scope_names_it() -> None:
    gateway = _gateway()
    gateway.list_users.side_effect = _refusal("user listing", 403)

    with pytest.raises(InsufficientPermissionsError, match="settings.users.read"):
        _run("hubspot_users", _context(gateway))


def test_an_outage_is_not_a_missing_scope() -> None:
    gateway = _gateway()
    gateway.get_record_viewers.side_effect = _refusal("record viewers", 503)

    with pytest.raises(UnexpectedValidationError):
        _run("hubspot_record_viewers", _context(gateway))


def test_viewers_are_probed_on_a_record_of_a_configured_type() -> None:
    gateway = _gateway()

    _run("hubspot_record_viewers", _context(gateway, object_types=["companies"]))

    gateway.get_record_viewers.assert_called_once_with(
        portal_id="46399533",
        object_type=HubSpotObjectType.COMPANIES,
        record_ids=["1"],
    )


@pytest.mark.parametrize(
    "check_id",
    ["hubspot_associations", "hubspot_notes", "hubspot_record_viewers"],
)
def test_an_empty_portal_has_nothing_to_probe(check_id: str) -> None:
    gateway = _gateway()
    gateway.list_records.return_value = HubSpotPage(items=[])

    _run(check_id, _context(gateway))

    assert gateway.list_records.call_count == len(HubSpotObjectType)
    gateway.list_associations.assert_not_called()
    gateway.get_record_viewers.assert_not_called()


def test_a_record_without_notes_reads_none() -> None:
    gateway = _gateway()
    gateway.list_associations.return_value = HubSpotPage(items=[])

    _run("hubspot_notes", _context(gateway))

    gateway.list_associations.assert_called_once_with(
        object_type=HubSpotObjectType.TICKETS,
        object_id="1",
        to_object_type="notes",
        limit=1,
    )
    gateway.read_records.assert_not_called()


def _connector(gateway: MagicMock) -> HubSpotConnector:
    connector = HubSpotConnector(object_types=["deals"])
    connector._ops = gateway
    return connector


def test_perm_sync_validation_probes_viewers_on_the_configured_types() -> None:
    gateway = _gateway()

    validate_perm_sync(_connector(gateway))

    gateway.list_users.assert_called_once_with(limit=1)
    gateway.get_record_viewers.assert_called_once_with(
        portal_id="46399533",
        object_type=HubSpotObjectType.DEALS,
        record_ids=["1"],
    )


def test_perm_sync_validation_fails_on_a_missing_users_scope() -> None:
    gateway = _gateway()
    gateway.list_users.side_effect = _refusal("user listing", 403)

    with pytest.raises(InsufficientPermissionsError, match="settings.users.read"):
        validate_perm_sync(_connector(gateway))
