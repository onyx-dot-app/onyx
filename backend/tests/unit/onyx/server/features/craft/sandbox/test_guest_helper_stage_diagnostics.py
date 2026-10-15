"""Synchronous helper diagnostics preserve calls and exclude private payloads."""

from __future__ import annotations

import json
import logging
from unittest.mock import Mock
from uuid import UUID

import pytest

from onyx.server.features.build.sandbox import kubernetes_runtime
from onyx.server.features.build.sandbox.exec import ExecClient, FramedStdin
from onyx.server.features.build.sandbox.image.guest.security import GUEST_PYTHON
from onyx.server.features.build.sandbox.kubernetes_runtime import KubernetesRuntime
from onyx.server.features.build.sandbox.models import ExecResult, SandboxExecError

_SANDBOX_ID = UUID("12345678-1234-1234-1234-1234567890ab")
_METADATA: dict[str, object] = {
    "mount_path": "/workspace/managed/private-path",
    "password": "metadata-password-secret",
    "command": ["command-argument-secret"],
    "nested": {"token": "nested-token-secret"},
}
_STDIN = b"stdin-secret"
_PREFIX = (
    "Guest helper operation=push-managed "
    "sandbox_id=12345678-1234-1234-1234-1234567890ab "
)


@pytest.fixture
def runtime() -> KubernetesRuntime:
    runtime = object.__new__(KubernetesRuntime)
    runtime._exec = Mock(spec=ExecClient)
    return runtime


def test_success_logs_each_stage_and_preserves_exec_inputs_and_result(
    runtime: KubernetesRuntime,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    result = ExecResult(stdout=b"stdout-secret", stderr="stderr-secret", returncode=7)
    target = Mock(return_value=("sandbox-safe", 17.25))
    run = Mock(return_value=result)
    monkeypatch.setattr(runtime, "_helper_target", target)
    monkeypatch.setattr(runtime._exec, "run", run)
    monkeypatch.setattr(
        kubernetes_runtime,
        "time",
        Mock(monotonic=Mock(side_effect=[100.0, 102.0, 102.0, 105.0])),
    )

    with caplog.at_level(logging.INFO):
        actual = runtime.helper(
            _SANDBOX_ID, "push-managed", _METADATA, stdin=_STDIN, timeout=20.0
        )

    assert actual is result
    target.assert_called_once_with(_SANDBOX_ID, 20.0)
    run.assert_called_once_with(
        "sandbox-safe",
        [
            GUEST_PYTHON,
            "-I",
            "-m",
            "onyx_guest",
            "push-managed",
            json.dumps(_METADATA, separators=(",", ":")),
        ],
        stdin=FramedStdin(_STDIN),
        timeout=17.25,
    )
    assert run.call_args.kwargs["stdin"].source is _STDIN
    assert caplog.messages == [
        _PREFIX
        + "stage=metadata_target outcome=start elapsed_seconds=0.000 budget_seconds=20.000",
        _PREFIX
        + "stage=metadata_target outcome=success elapsed_seconds=2.000 budget_seconds=20.000",
        _PREFIX
        + "stage=exec outcome=start elapsed_seconds=0.000 budget_seconds=17.250",
        _PREFIX
        + "stage=exec outcome=success elapsed_seconds=3.000 budget_seconds=17.250",
    ]
    assert all(record.levelno == logging.INFO for record in caplog.records)


@pytest.mark.parametrize("failed_stage", ["metadata_target", "exec"])
def test_failure_logs_only_its_stage_and_exception_class(
    runtime: KubernetesRuntime,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failed_stage: str,
) -> None:
    error = SandboxExecError(
        "exception-message-secret", stderr="exception-stderr-secret"
    )
    target = Mock(return_value=("sandbox-safe", 17.25))
    run = Mock(side_effect=error)
    ticks = [100.0, 102.0, 102.0, 105.0]
    if failed_stage == "metadata_target":
        target.side_effect = error
        ticks = [100.0, 102.0]
    monkeypatch.setattr(runtime, "_helper_target", target)
    monkeypatch.setattr(runtime._exec, "run", run)
    monkeypatch.setattr(
        kubernetes_runtime, "time", Mock(monotonic=Mock(side_effect=ticks))
    )

    with caplog.at_level(logging.INFO), pytest.raises(SandboxExecError) as caught:
        runtime.helper(
            _SANDBOX_ID, "push-managed", _METADATA, stdin=_STDIN, timeout=20.0
        )

    assert caught.value is error
    expected = [
        _PREFIX
        + "stage=metadata_target outcome=start elapsed_seconds=0.000 budget_seconds=20.000"
    ]
    if failed_stage == "exec":
        expected.extend(
            [
                _PREFIX
                + "stage=metadata_target outcome=success elapsed_seconds=2.000 budget_seconds=20.000",
                _PREFIX
                + "stage=exec outcome=start elapsed_seconds=0.000 budget_seconds=17.250",
                _PREFIX
                + "stage=exec outcome=failure elapsed_seconds=3.000 budget_seconds=17.250 error_type=SandboxExecError",
            ]
        )
        assert run.call_args.kwargs["timeout"] == 17.25
    else:
        expected.append(
            _PREFIX
            + "stage=metadata_target outcome=failure elapsed_seconds=2.000 budget_seconds=20.000 error_type=SandboxExecError"
        )
        run.assert_not_called()
    assert caplog.messages == expected
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.parametrize(
    ("operation", "metadata", "error_type"),
    [("serve", {}, ValueError), ("push-managed", {"invalid": object()}, TypeError)],
)
def test_command_validation_precedes_metadata_lookup_and_diagnostics(
    runtime: KubernetesRuntime,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    operation: str,
    metadata: dict[str, object],
    error_type: type[Exception],
) -> None:
    target = Mock()
    monkeypatch.setattr(runtime, "_helper_target", target)

    with caplog.at_level(logging.INFO), pytest.raises(error_type):
        runtime.helper(_SANDBOX_ID, operation, metadata, timeout=20.0)

    target.assert_not_called()
    assert caplog.messages == []
