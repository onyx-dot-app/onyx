from unittest.mock import MagicMock

import pytest

from ee.onyx.connectors import capability_checks as ee_capability_checks
from ee.onyx.connectors.capability_checks import (
    get_applicable_perm_sync_capabilities,
    get_perm_sync_capability_checks,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors import source_operations as source_operations_module
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CredentialCapability,
)
from onyx.connectors.interfaces import BaseConnector
from onyx.connectors.source_operations import SourceOperations


class _NamedCheck(CapabilityCheck):
    """Minimal concrete named check; ``run`` never executes in these tests."""

    def run(self, context: CapabilityCheckContext) -> None:
        raise NotImplementedError


def test_slack_perm_sync_capabilities_exclude_group_sync() -> None:
    """Verifies Slack applicability: doc sync yes, group sync no (by design)."""
    # Under test and postcondition.
    assert get_applicable_perm_sync_capabilities(DocumentSource.SLACK) == {
        CredentialCapability.DOC_PERMISSION_SYNC
    }


def test_google_drive_has_both_perm_sync_capabilities() -> None:
    """Verifies a both-capability source resolves from the sync registry."""
    # Under test and postcondition.
    assert get_applicable_perm_sync_capabilities(DocumentSource.GOOGLE_DRIVE) == {
        CredentialCapability.DOC_PERMISSION_SYNC,
        CredentialCapability.EXTERNAL_GROUP_SYNC,
    }


def test_censoring_only_source_has_no_perm_sync_capabilities() -> None:
    """
    Verifies Salesforce (query-time censoring only) maps to no capabilities.
    """
    # Under test and postcondition.
    assert get_applicable_perm_sync_capabilities(DocumentSource.SALESFORCE) == set()


def test_probeless_sync_source_gets_no_fallback() -> None:
    """
    Verifies the no-trivial-pass rule: Gmail is sync-capable, but its legacy
    ``validate_perm_sync`` dispatch is a no-op, so no fallback is synthesized
    and no verdict can pass on the basis of a no-op probe.
    """
    # Under test and postcondition.
    assert get_perm_sync_capability_checks(DocumentSource.GMAIL) == []


def test_slack_registers_named_doc_sync_checks_only() -> None:
    """
    Verifies Slack's registered perm-sync suite: named DOC_PERMISSION_SYNC
    checks (no fallback), and nothing under EXTERNAL_GROUP_SYNC, which is not
    applicable for Slack by design.
    """
    # Under test.
    checks = get_perm_sync_capability_checks(DocumentSource.SLACK)

    # Postcondition.
    assert checks
    assert {check.capability for check in checks} == {
        CredentialCapability.DOC_PERMISSION_SYNC
    }
    assert not any(check.is_fallback for check in checks)


def test_fallback_synthesis_respects_applicability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verifies a probe-bearing source only gets fallbacks for its applicable
    capabilities.
    """
    # Precondition.
    # Every probe-bearing source supports both sync capabilities today, so pin
    # applicability to doc sync only.
    monkeypatch.setattr(
        ee_capability_checks,
        "get_applicable_perm_sync_capabilities",
        lambda _source: {CredentialCapability.DOC_PERMISSION_SYNC},
    )

    # Under test.
    checks = get_perm_sync_capability_checks(DocumentSource.GOOGLE_DRIVE)

    # Postcondition.
    assert [check.capability for check in checks] == [
        CredentialCapability.DOC_PERMISSION_SYNC
    ]
    assert checks[0].is_fallback is True
    assert checks[0].check_id == "google_drive_perm_sync"


def test_named_checks_ignore_the_probe_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verifies the allowlist gates only fallback synthesis: a probe-less source
    with registered named checks still returns them.
    """
    # Precondition.
    # The ratchet requires a gateway wherever named checks register.
    monkeypatch.setattr(source_operations_module, "_SOURCE_OPERATIONS_BY_SOURCE", {})

    class _SlackOperations(SourceOperations):
        source = DocumentSource.SLACK
        sdk_modules = ()

    named_check = _NamedCheck(
        capability=CredentialCapability.DOC_PERMISSION_SYNC,
        check_id="slack_named_check",
        display_name="Named check",
    )
    monkeypatch.setitem(
        ee_capability_checks._DOC_PERMISSION_SYNC_CHECKS_BY_SOURCE,
        DocumentSource.SLACK,
        [named_check],
    )

    # Under test and postcondition.
    assert get_perm_sync_capability_checks(DocumentSource.SLACK) == [named_check]


def test_unregistered_sync_source_gets_shared_fallback_checks() -> None:
    """
    Verifies fallback synthesis for a sync-capable source with no named checks.
    """
    # Under test.
    checks = get_perm_sync_capability_checks(DocumentSource.GOOGLE_DRIVE)

    # Postcondition.
    # One fallback per applicable capability, sharing a single check_id (and
    # class) so the runner executes it once and mirrors.
    assert {check.capability for check in checks} == {
        CredentialCapability.DOC_PERMISSION_SYNC,
        CredentialCapability.EXTERNAL_GROUP_SYNC,
    }
    assert all(check.is_fallback for check in checks)
    assert len({type(check) for check in checks}) == 1
    assert {check.check_id for check in checks} == {"google_drive_perm_sync"}


def test_registered_checks_clobber_only_their_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verifies named checks clobber the fallback per capability, not per source.
    """
    # Precondition.
    # Nothing is registered at the framework layer, so register a gateway and a
    # named doc-sync check the way a per-connector session would (the ratchet
    # requires the gateway).
    monkeypatch.setattr(source_operations_module, "_SOURCE_OPERATIONS_BY_SOURCE", {})

    class _GoogleDriveOperations(SourceOperations):
        source = DocumentSource.GOOGLE_DRIVE
        sdk_modules = ()

    named_check = _NamedCheck(
        capability=CredentialCapability.DOC_PERMISSION_SYNC,
        check_id="google_drive_named_check",
        display_name="Named check",
    )
    monkeypatch.setitem(
        ee_capability_checks._DOC_PERMISSION_SYNC_CHECKS_BY_SOURCE,
        DocumentSource.GOOGLE_DRIVE,
        [named_check],
    )

    # Under test.
    checks = get_perm_sync_capability_checks(DocumentSource.GOOGLE_DRIVE)

    # Postcondition.
    # Doc sync uses the named check; group sync, applicable but still
    # unregistered, keeps its fallback.
    doc_sync_checks = [
        check
        for check in checks
        if check.capability == CredentialCapability.DOC_PERMISSION_SYNC
    ]
    group_sync_checks = [
        check
        for check in checks
        if check.capability == CredentialCapability.EXTERNAL_GROUP_SYNC
    ]
    assert doc_sync_checks == [named_check]
    assert len(group_sync_checks) == 1
    assert group_sync_checks[0].is_fallback is True


def test_censoring_only_source_gets_no_fallback_checks() -> None:
    """Verifies no fallback is synthesized when neither capability applies."""
    # Under test and postcondition.
    assert get_perm_sync_capability_checks(DocumentSource.SALESFORCE) == []


def test_fallback_check_calls_validate_perm_sync() -> None:
    """Verifies the synthesized fallback wraps ``validate_perm_sync``."""
    # Precondition.
    connector = MagicMock(spec=BaseConnector)
    context = CapabilityCheckContext(
        source=DocumentSource.GOOGLE_DRIVE,
        credential_json={},
        connector=connector,
    )
    check = get_perm_sync_capability_checks(DocumentSource.GOOGLE_DRIVE)[0]

    # Under test.
    check.run(context)

    # Postcondition.
    connector.validate_perm_sync.assert_called_once_with()
