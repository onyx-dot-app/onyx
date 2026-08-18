"""Unit tests for the derived capability-run ceilings."""

from datetime import timedelta

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.capability_checks import runner
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
)


class _StubCheck(CapabilityCheck):
    def run(self, context: CapabilityCheckContext) -> None:  # noqa: ARG002
        raise AssertionError("Ceiling math must not execute checks.")


def test_ceiling_sums_distinct_guards_once_plus_instantiation_slack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Precondition. Two capabilities mirror one check (a single execution at
    # run time), plus one check on the default hang guard.
    checks = [
        _StubCheck(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="mirrored",
            display_name="Mirrored",
            timeout_seconds=100,
        ),
        _StubCheck(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="mirrored",
            display_name="Mirrored",
            timeout_seconds=100,
        ),
        _StubCheck(
            capability=CredentialCapability.INDEXING,
            check_id="default_guard",
            display_name="Default guard",
        ),
    ]
    monkeypatch.setattr(runner, "get_capability_checks", lambda _source: checks)

    # Under test.
    ceiling = runner.capability_check_run_ceiling_seconds(DocumentSource.SLACK)
    stale_after = runner.capability_check_run_stale_after(DocumentSource.SLACK)

    # Postcondition. One slack unit for instantiation, the mirrored guard
    # counted once, and one default guard; staleness allows queue wait plus
    # execution.
    assert ceiling == 2 * runner.CAPABILITY_CHECK_TIMEOUT_SECONDS + 100
    assert stale_after == timedelta(seconds=2 * ceiling)
