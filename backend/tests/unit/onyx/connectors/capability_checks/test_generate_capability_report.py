from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks import runner as runner_module
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckStatus,
    CapabilityCheckTrigger,
    CapabilityVerdict,
    CredentialCapability,
)
from onyx.connectors.capability_checks.runner import generate_capability_report
from onyx.connectors.interfaces import BaseConnector


def _make_check(
    run: Callable[[CapabilityCheckContext], None],
    check_id: str,
    requires_connector_instance: bool = True,
    requires_connector_config: bool = False,
) -> CapabilityCheck:
    return CapabilityCheck(
        capability=CredentialCapability.INDEXING,
        check_id=check_id,
        display_name="Dummy check",
        run=run,
        requires_connector_instance=requires_connector_instance,
        requires_connector_config=requires_connector_config,
    )


def _make_credential() -> MagicMock:
    credential = MagicMock()
    credential.id = 7
    credential.source = DocumentSource.GITHUB
    credential.credential_json = None
    return credential


def _patch_runner_environment(
    monkeypatch: pytest.MonkeyPatch,
    checks: list[CapabilityCheck],
    probe_config: dict[str, Any] | None,
    instantiate_error: Exception | None = None,
) -> MagicMock:
    """Stubs registry lookup and connector construction around the orchestrator.

    Returns the ``instantiate_connector`` mock for call-shape assertions.
    """
    connector_class = MagicMock()
    connector_class.minimal_probe_config.return_value = probe_config
    monkeypatch.setattr(
        runner_module,
        "identify_connector_class",
        MagicMock(return_value=connector_class),
    )
    # The instantiated connector must satisfy ``CapabilityCheckContext``'s
    # isinstance validation, hence the spec.
    instantiate = MagicMock(return_value=MagicMock(spec=BaseConnector))
    if instantiate_error is not None:
        instantiate.side_effect = instantiate_error
    monkeypatch.setattr(runner_module, "instantiate_connector", instantiate)
    monkeypatch.setattr(
        runner_module, "get_capability_checks", MagicMock(return_value=checks)
    )
    monkeypatch.setattr(
        runner_module,
        "get_applicable_capabilities",
        MagicMock(return_value={CredentialCapability.INDEXING}),
    )
    return instantiate


def test_configless_run_uses_probe_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies a config-less run instantiates via ``minimal_probe_config``."""
    # Precondition.
    check = _make_check(MagicMock(return_value=None), check_id="instance_check")
    instantiate = _patch_runner_environment(monkeypatch, [check], probe_config={})
    db_session = MagicMock()
    credential = _make_credential()

    # Under test.
    report = generate_capability_report(db_session, credential)

    # Postcondition.
    instantiate.assert_called_once_with(
        db_session=db_session,
        source=DocumentSource.GITHUB,
        input_type=None,
        connector_specific_config={},
        credential=credential,
    )
    assert report.credential_id == 7
    assert report.source == DocumentSource.GITHUB
    assert report.connector_id is None
    assert report.trigger == CapabilityCheckTrigger.MANUAL
    assert report.check_results[0].status == CapabilityCheckStatus.PASSED
    assert report.verdicts == {
        CredentialCapability.INDEXING: CapabilityVerdict.PASSED,
        CredentialCapability.DOC_PERMISSION_SYNC: CapabilityVerdict.NOT_APPLICABLE,
        CredentialCapability.EXTERNAL_GROUP_SYNC: CapabilityVerdict.NOT_APPLICABLE,
    }


def test_probe_config_none_skips_instance_requiring_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies that a None probe config degrades to skips, not a crash."""
    # Precondition.
    # One check needs an instance, the other is a pure credential-shape check.
    instance_check = _make_check(
        MagicMock(return_value=None), check_id="instance_check"
    )
    shape_check = _make_check(
        MagicMock(return_value=None),
        check_id="shape_check",
        requires_connector_instance=False,
    )
    instantiate = _patch_runner_environment(
        monkeypatch, [instance_check, shape_check], probe_config=None
    )

    # Under test.
    report = generate_capability_report(MagicMock(), _make_credential())

    # Postcondition.
    instantiate.assert_not_called()
    statuses = {result.check_id: result.status for result in report.check_results}
    assert statuses == {
        "instance_check": CapabilityCheckStatus.SKIPPED,
        "shape_check": CapabilityCheckStatus.PASSED,
    }


def test_instantiation_failure_degrades_to_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verifies that a raising constructor skips instance checks, not the run.
    """
    # Precondition.
    check = _make_check(MagicMock(return_value=None), check_id="instance_check")
    _patch_runner_environment(
        monkeypatch,
        [check],
        probe_config={},
        instantiate_error=RuntimeError("Constructor requires a real config."),
    )

    # Under test.
    report = generate_capability_report(MagicMock(), _make_credential())

    # Postcondition.
    assert report.check_results[0].status == CapabilityCheckStatus.SKIPPED
    assert report.verdicts[CredentialCapability.INDEXING] == CapabilityVerdict.SKIPPED


def test_real_config_unlocks_config_requiring_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verifies that a supplied config is used to instantiate and reaches checks.
    """
    # Precondition.
    check = _make_check(
        MagicMock(return_value=None),
        check_id="config_check",
        requires_connector_config=True,
    )
    instantiate = _patch_runner_environment(monkeypatch, [check], probe_config=None)
    connector_specific_config = {"repositories": "onyx"}

    # Under test.
    report = generate_capability_report(
        MagicMock(),
        _make_credential(),
        connector_specific_config=connector_specific_config,
        connector_id=42,
        trigger=CapabilityCheckTrigger.CC_PAIR_VALIDATION,
    )

    # Postcondition.
    # The real config wins over the None probe config.
    assert (
        instantiate.call_args.kwargs["connector_specific_config"]
        == connector_specific_config
    )
    assert report.connector_id == 42
    assert report.trigger == CapabilityCheckTrigger.CC_PAIR_VALIDATION
    assert report.check_results[0].status == CapabilityCheckStatus.PASSED
