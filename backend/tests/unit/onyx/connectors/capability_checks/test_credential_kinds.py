"""Checks limited to some credential kinds, and how the kind is resolved."""

from typing import Any

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks import credential_kinds
from onyx.connectors.capability_checks.credential_kinds import resolve_credential_kind
from onyx.connectors.capability_checks.draft_runs import (
    DraftCheckStateKind,
    apply_check_result,
    decide_draft_check_state,
)
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckStatus,
    CredentialCapability,
)
from onyx.connectors.capability_checks.runner import run_capability_checks

_SERVICE_ACCOUNT = "service_account"


class _ServiceAccountCheck(CapabilityCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="test_service_account_only",
            display_name="Service account only",
            requires_connector_instance=False,
            credential_kinds=frozenset({_SERVICE_ACCOUNT}),
        )
        self.ran = False

    def run(self, context: CapabilityCheckContext) -> None:  # noqa: ARG002
        self.ran = True


def _context(credential_kind: str | None) -> CapabilityCheckContext:
    return CapabilityCheckContext(
        source=DocumentSource.GOOGLE_DRIVE,
        credential_json={},
        credential_kind=credential_kind,
    )


def test_check_of_another_kind_is_not_applicable() -> None:
    # Precondition.
    check = _ServiceAccountCheck()

    # Under test.
    (result,) = run_capability_checks([check], _context("oauth"))

    # Postcondition.
    assert check.ran is False
    assert result.status == CapabilityCheckStatus.SKIPPED
    assert result.applicable is False
    assert "oauth" in result.message


@pytest.mark.parametrize("credential_kind", [_SERVICE_ACCOUNT, None])
def test_check_runs_for_its_kind_or_an_unknown_kind(
    credential_kind: str | None,
) -> None:
    # Precondition.
    check = _ServiceAccountCheck()

    # Under test.
    (result,) = run_capability_checks([check], _context(credential_kind))

    # Postcondition.
    assert check.ran is True
    assert result.status == CapabilityCheckStatus.PASSED


def test_draft_plan_shows_a_check_of_another_kind_as_not_applicable() -> None:
    # Under test.
    state = decide_draft_check_state(_ServiceAccountCheck(), _context("oauth"))

    # Postcondition.
    assert state.state == DraftCheckStateKind.NOT_APPLICABLE


def test_draft_run_result_that_does_not_apply_is_not_applicable() -> None:
    """A kind the planner did not know resolves when the run reads the
    credential."""
    # Precondition.
    check = _ServiceAccountCheck()
    state = decide_draft_check_state(check, _context(None))
    assert state.state == DraftCheckStateKind.PENDING
    (result,) = run_capability_checks([check], _context("oauth"))

    # Under test.
    apply_check_result(state, result)

    # Postcondition.
    assert state.state == DraftCheckStateKind.NOT_APPLICABLE


def test_resolve_uses_the_source_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    # Precondition.
    def _resolver(credential_json: dict[str, Any]) -> str | None:
        return _SERVICE_ACCOUNT if "key" in credential_json else None

    monkeypatch.setattr(
        credential_kinds,
        "_CREDENTIAL_KIND_RESOLVERS",
        {DocumentSource.GOOGLE_DRIVE: _resolver},
    )

    # Under test and postcondition.
    assert (
        resolve_credential_kind(DocumentSource.GOOGLE_DRIVE, {"key": "x"})
        == _SERVICE_ACCOUNT
    )
    assert resolve_credential_kind(DocumentSource.GOOGLE_DRIVE, {}) is None
    assert resolve_credential_kind(DocumentSource.SLACK, {"key": "x"}) is None
