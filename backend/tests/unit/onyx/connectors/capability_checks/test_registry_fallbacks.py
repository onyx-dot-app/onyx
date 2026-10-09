from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors import source_operations as source_operations_module
from onyx.connectors.capability_checks import registry
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CredentialCapability,
)
from onyx.connectors.capability_checks.registry import (
    get_applicable_capabilities,
    get_capability_checks,
)
from onyx.connectors.interfaces import BaseConnector
from onyx.connectors.source_operations import SourceOperations


class _NamedCheck(CapabilityCheck):
    """Minimal concrete named check; ``run`` never executes in these tests."""

    def run(self, context: CapabilityCheckContext) -> None:
        raise NotImplementedError


def test_unregistered_source_gets_connector_settings_fallback() -> None:
    """
    Verifies fallback synthesis for a source with no named INDEXING checks.
    """
    # Under test.
    checks = get_capability_checks(DocumentSource.GITHUB)

    # Postcondition.
    # On OSS builds only the synthesized INDEXING check exists.
    indexing_checks = [
        check for check in checks if check.capability == CredentialCapability.INDEXING
    ]
    assert len(indexing_checks) == 1
    fallback = indexing_checks[0]
    assert fallback.check_id == "github_connector_settings"
    assert fallback.is_fallback is True
    assert fallback.required is True
    assert fallback.requires_connector_instance is True


def test_registered_source_gets_no_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies that registered named checks clobber the INDEXING fallback."""
    # Precondition.
    # Nothing is registered at the framework layer, so register a gateway and a
    # named check the way a per-connector session would (the ratchet requires
    # the gateway).
    monkeypatch.setattr(source_operations_module, "_SOURCE_OPERATIONS_BY_SOURCE", {})

    class _GithubOperations(SourceOperations):
        source = DocumentSource.GITHUB
        sdk_modules = ()

    named_check = _NamedCheck(
        capability=CredentialCapability.INDEXING,
        check_id="github_named_check",
        display_name="Named check",
    )
    monkeypatch.setitem(
        registry._INDEXING_CHECKS_BY_SOURCE, DocumentSource.GITHUB, [named_check]
    )

    # Under test.
    checks = get_capability_checks(DocumentSource.GITHUB)

    # Postcondition.
    indexing_checks = [
        check for check in checks if check.capability == CredentialCapability.INDEXING
    ]
    assert indexing_checks == [named_check]
    assert not any(check.is_fallback for check in indexing_checks)


def test_fallback_check_calls_validate_connector_settings() -> None:
    """
    Verifies the synthesized fallback wraps ``validate_connector_settings``.
    """
    # Precondition.
    connector = MagicMock(spec=BaseConnector)
    context = CapabilityCheckContext(
        source=DocumentSource.GITHUB,
        credential_json={},
        connector=connector,
    )
    check = get_capability_checks(DocumentSource.GITHUB)[0]

    # Under test.
    check.run(context)

    # Postcondition.
    connector.validate_connector_settings.assert_called_once_with()


def test_oss_build_only_has_indexing_capability() -> None:
    """Verifies the EE-noop path: perm-sync capabilities do not exist on OSS."""
    # Under test and postcondition.
    # Google Drive is sync-capable on EE, so it is the strongest witness that
    # the OSS noop returns INDEXING only.
    assert get_applicable_capabilities(DocumentSource.GOOGLE_DRIVE) == {
        CredentialCapability.INDEXING
    }
