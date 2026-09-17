import pytest

from ee.onyx.connectors import capability_checks as ee_capability_checks
from ee.onyx.connectors.capability_checks import get_perm_sync_capability_checks
from onyx.configs.constants import DocumentSource
from onyx.connectors import source_operations as source_operations_module
from onyx.connectors.capability_checks import registry
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CredentialCapability,
)
from onyx.connectors.capability_checks.registry import get_capability_checks
from onyx.connectors.source_operations import SourceOperations
from tests.unit.onyx.connectors.source_operation_harnesses import (
    import_all_source_operation_gateways,
)


class _NamedCheck(CapabilityCheck):
    """Minimal concrete named check; ``run`` never executes in these tests."""

    def run(self, context: CapabilityCheckContext) -> None:
        raise NotImplementedError


@pytest.fixture
def isolated_gateway_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolates the gateway registry so test gateways never leak globally."""
    monkeypatch.setattr(source_operations_module, "_SOURCE_OPERATIONS_BY_SOURCE", {})


def _register_github_gateway() -> None:
    class _GithubOperations(SourceOperations):
        source = DocumentSource.GITHUB
        sdk_modules = ()


@pytest.mark.usefixtures("isolated_gateway_registry")
def test_named_indexing_checks_require_a_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies the ratchet: no named INDEXING checks without a gateway."""
    # Precondition.
    named_check = _NamedCheck(
        capability=CredentialCapability.INDEXING,
        check_id="github_named_check",
        display_name="Named check",
    )
    monkeypatch.setitem(
        registry._INDEXING_CHECKS_BY_SOURCE, DocumentSource.GITHUB, [named_check]
    )

    # Under test and postcondition.
    with pytest.raises(AssertionError, match="source-operations gateway"):
        get_capability_checks(DocumentSource.GITHUB)


@pytest.mark.usefixtures("isolated_gateway_registry")
def test_named_indexing_checks_pass_with_a_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies a migrated source registers named checks freely."""
    # Precondition.
    _register_github_gateway()
    named_check = _NamedCheck(
        capability=CredentialCapability.INDEXING,
        check_id="github_named_check",
        display_name="Named check",
    )
    monkeypatch.setitem(
        registry._INDEXING_CHECKS_BY_SOURCE, DocumentSource.GITHUB, [named_check]
    )

    # Under test and postcondition.
    assert named_check in get_capability_checks(DocumentSource.GITHUB)


@pytest.mark.usefixtures("isolated_gateway_registry")
def test_named_perm_sync_checks_require_a_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies the ratchet applies to the EE perm-sync registries too."""
    # Precondition.
    named_check = _NamedCheck(
        capability=CredentialCapability.DOC_PERMISSION_SYNC,
        check_id="github_named_check",
        display_name="Named check",
    )
    monkeypatch.setitem(
        ee_capability_checks._DOC_PERMISSION_SYNC_CHECKS_BY_SOURCE,
        DocumentSource.GITHUB,
        [named_check],
    )

    # Under test and postcondition.
    with pytest.raises(AssertionError, match="source-operations gateway"):
        get_perm_sync_capability_checks(DocumentSource.GITHUB)


@pytest.mark.usefixtures("isolated_gateway_registry")
def test_named_perm_sync_checks_pass_with_a_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies a migrated source registers named perm-sync checks freely."""
    # Precondition.
    _register_github_gateway()
    named_check = _NamedCheck(
        capability=CredentialCapability.DOC_PERMISSION_SYNC,
        check_id="github_named_check",
        display_name="Named check",
    )
    monkeypatch.setitem(
        ee_capability_checks._DOC_PERMISSION_SYNC_CHECKS_BY_SOURCE,
        DocumentSource.GITHUB,
        [named_check],
    )

    # Under test and postcondition.
    assert named_check in get_perm_sync_capability_checks(DocumentSource.GITHUB)


@pytest.mark.usefixtures("isolated_gateway_registry")
def test_fallback_path_needs_no_gateway() -> None:
    """Verifies unmigrated sources keep their fallback coverage untouched."""
    # Under test.
    checks = get_capability_checks(DocumentSource.GITHUB)

    # Postcondition.
    assert any(check.is_fallback for check in checks)


def test_every_source_resolves_checks_without_tripping_the_ratchet() -> None:
    """
    Verifies real registrations satisfy the ratchet in CI rather than first
    firing at report time, and smoke-tests fallback synthesis for the whole
    enum.
    """
    # Precondition.
    import_all_source_operation_gateways()

    # Under test and postcondition.
    for source in DocumentSource:
        assert get_capability_checks(source)


@pytest.mark.usefixtures("enable_ee")
def test_every_source_resolves_checks_with_ee_enabled() -> None:
    """Verifies the same holds with EE resolution on."""
    # Precondition.
    import_all_source_operation_gateways()

    # Under test and postcondition.
    for source in DocumentSource:
        assert get_capability_checks(source)
