from collections.abc import Callable
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
from onyx.connectors.exceptions import CredentialInvalidError
from onyx.connectors.interfaces import BaseConnector
from onyx.connectors.source_operations import SourceOperations


class _CallableCheck(CapabilityCheck):
    """Concrete check that delegates ``run`` to an injected callable."""

    def __init__(
        self,
        run: Callable[[CapabilityCheckContext], None],
        check_id: str,
        requires_connector_instance: bool = True,
        requires_connector_config: bool = False,
    ) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id=check_id,
            display_name="Dummy check",
            requires_connector_instance=requires_connector_instance,
            requires_connector_config=requires_connector_config,
        )
        self._run = run

    def run(self, context: CapabilityCheckContext) -> None:
        self._run(context)


def _make_credential() -> MagicMock:
    credential = MagicMock()
    credential.id = 7
    credential.source = DocumentSource.GITHUB
    credential.credential_json = None
    return credential


def _patch_runner_environment(
    monkeypatch: pytest.MonkeyPatch,
    checks: list[CapabilityCheck],
    instantiate_error: Exception | None = None,
) -> MagicMock:
    """Stubs registry lookup and connector construction around the orchestrator.

    Returns the ``instantiate_connector`` mock for call-shape assertions.
    """
    monkeypatch.setattr(
        runner_module,
        "identify_connector_class",
        MagicMock(return_value=MagicMock()),
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


def test_configless_run_attempts_empty_config_instantiation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies a config-less run instantiates with an empty config."""
    # Precondition.
    check = _CallableCheck(MagicMock(return_value=None), check_id="instance_check")
    instantiate = _patch_runner_environment(monkeypatch, [check])
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


def test_instantiation_failure_still_runs_credential_only_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies a raising constructor degrades to skips, not a crash."""
    # Precondition.
    # One check needs an instance, the other is a pure credential-shape check.
    instance_check = _CallableCheck(
        MagicMock(return_value=None), check_id="instance_check"
    )
    shape_check = _CallableCheck(
        MagicMock(return_value=None),
        check_id="shape_check",
        requires_connector_instance=False,
    )
    _patch_runner_environment(
        monkeypatch,
        [instance_check, shape_check],
        instantiate_error=RuntimeError("Constructor requires a real config."),
    )

    # Under test.
    report = generate_capability_report(MagicMock(), _make_credential())

    # Postcondition.
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
    check = _CallableCheck(MagicMock(return_value=None), check_id="instance_check")
    _patch_runner_environment(
        monkeypatch,
        [check],
        instantiate_error=RuntimeError("Constructor requires a real config."),
    )

    # Under test.
    report = generate_capability_report(MagicMock(), _make_credential())

    # Postcondition.
    assert report.check_results[0].status == CapabilityCheckStatus.SKIPPED
    assert report.verdicts[CredentialCapability.INDEXING] == CapabilityVerdict.SKIPPED


def test_supplied_config_instantiation_failure_is_surfaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verifies construction failure with a real config is FAILED, not SKIPPED.
    """
    # Precondition.
    check = _CallableCheck(MagicMock(return_value=None), check_id="instance_check")
    _patch_runner_environment(
        monkeypatch,
        [check],
        instantiate_error=CredentialInvalidError("Missing `slack_bot_token` key."),
    )

    # Under test.
    report = generate_capability_report(
        MagicMock(),
        _make_credential(),
        connector_specific_config={"channels": ["general"]},
        connector_id=42,
    )

    # Postcondition.
    assert report.check_results[0].status == CapabilityCheckStatus.FAILED
    assert report.check_results[0].error_type == "CredentialInvalidError"
    assert report.verdicts[CredentialCapability.INDEXING] == CapabilityVerdict.FAILED


def test_real_config_unlocks_config_requiring_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verifies that a supplied config is used to instantiate and reaches checks.
    """
    # Precondition.
    check = _CallableCheck(
        MagicMock(return_value=None),
        check_id="config_check",
        requires_connector_config=True,
    )
    instantiate = _patch_runner_environment(monkeypatch, [check])
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
    # The real config, not the empty-config fallback, reaches instantiation.
    assert (
        instantiate.call_args.kwargs["connector_specific_config"]
        == connector_specific_config
    )
    assert report.connector_id == 42
    assert report.trigger == CapabilityCheckTrigger.CC_PAIR_VALIDATION
    assert report.check_results[0].status == CapabilityCheckStatus.PASSED


def test_registered_gateway_is_constructed_and_reaches_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verifies the runner constructs the registered gateway uniformly (provider
    plus the supplied config) and hands it to checks via the context.
    """
    # Precondition.
    seen_contexts: list[CapabilityCheckContext] = []
    check = _CallableCheck(
        seen_contexts.append,
        check_id="gateway_check",
        requires_connector_instance=False,
    )
    _patch_runner_environment(monkeypatch, [check])
    provider = MagicMock()
    monkeypatch.setattr(
        runner_module,
        "build_db_credentials_provider",
        MagicMock(return_value=provider),
    )
    gateway_instance = MagicMock(spec=SourceOperations)
    gateway_class = MagicMock(return_value=gateway_instance)
    monkeypatch.setattr(
        runner_module,
        "get_source_operations_class",
        MagicMock(return_value=gateway_class),
    )
    connector_specific_config = {"channels": ["general"]}

    # Under test.
    generate_capability_report(
        MagicMock(),
        _make_credential(),
        connector_specific_config=connector_specific_config,
    )

    # Postcondition.
    gateway_class.assert_called_once_with(
        credentials_provider=provider,
        connector_specific_config=connector_specific_config,
    )
    assert seen_contexts[0].source_operations is gateway_instance


def test_unregistered_source_gets_no_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies the context carries no gateway for unmigrated sources."""
    # Precondition.
    # Github has no registered gateway, so the real lookup returns None.
    seen_contexts: list[CapabilityCheckContext] = []
    check = _CallableCheck(
        seen_contexts.append,
        check_id="gateway_check",
        requires_connector_instance=False,
    )
    _patch_runner_environment(monkeypatch, [check])

    # Under test.
    generate_capability_report(MagicMock(), _make_credential())

    # Postcondition.
    assert seen_contexts[0].source_operations is None


def test_report_decrypt_emits_a_credential_audit_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verifies the report run's own decrypt is audited: it is a distinct decrypt
    site from ``instantiate_connector``, which may not have decrypted at all.
    """
    # Precondition.
    check = _CallableCheck(MagicMock(return_value=None), check_id="instance_check")
    _patch_runner_environment(monkeypatch, [check])
    emit = MagicMock()
    monkeypatch.setattr(runner_module, "emit_credential_access", emit)
    credential = _make_credential()
    credential.credential_json = MagicMock()
    credential.credential_json.get_value.return_value = {"token": "x"}

    # Under test.
    generate_capability_report(MagicMock(), credential)

    # Postcondition.
    emit.assert_called_once_with(
        credential_type="connector",
        provider=str(DocumentSource.GITHUB),
        row_id=7,
    )


def test_empty_credential_decrypts_nothing_and_emits_no_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies a credential-less row produces no phantom audit event."""
    # Precondition.
    check = _CallableCheck(MagicMock(return_value=None), check_id="instance_check")
    _patch_runner_environment(monkeypatch, [check])
    emit = MagicMock()
    monkeypatch.setattr(runner_module, "emit_credential_access", emit)

    # Under test.
    generate_capability_report(MagicMock(), _make_credential())

    # Postcondition.
    emit.assert_not_called()
