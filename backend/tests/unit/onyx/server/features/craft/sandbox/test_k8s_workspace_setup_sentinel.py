"""K8s workspace setup must fail loudly without the completion sentinel.

The Kubernetes exec client returns whatever output was buffered when
``_request_timeout`` lapses WITHOUT raising, and never raises on a nonzero
exit — so the sentinel in the exec output is the only reliable success
signal for ``setup_session_workspace``.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

import onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager as ksm
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.server.features.build.sandbox.models import CraftLLMProviderConfig
from onyx.server.features.build.sandbox.session_workspace import (
    WORKSPACE_SETUP_COMPLETE_SENTINEL,
)
from onyx.server.features.build.timeouts import WORKSPACE_SETUP_DEADLINE_SECONDS

_LLM_CONFIG = CraftLLMProviderConfig(
    provider="openai",
    model_name="gpt-test",
    api_key=None,
    api_base=None,
)


def _make_manager(monkeypatch: pytest.MonkeyPatch) -> KubernetesSandboxManager:
    mgr: KubernetesSandboxManager = object.__new__(KubernetesSandboxManager)
    mgr._namespace = "sandbox-test"  # type: ignore[attr-defined]
    mgr._stream_core_api = MagicMock()  # type: ignore[attr-defined]
    monkeypatch.setattr(
        mgr,
        "_load_agent_instructions",
        lambda **_kwargs: "agent instructions",
        raising=False,
    )
    return mgr


def _run_setup(monkeypatch: pytest.MonkeyPatch, exec_output: str) -> SimpleNamespace:
    mgr = _make_manager(monkeypatch)
    captured = SimpleNamespace(kwargs={})

    def fake_stream(*_args: Any, **kwargs: Any) -> str:
        captured.kwargs = kwargs
        return exec_output

    monkeypatch.setattr(ksm, "k8s_stream", fake_stream)
    mgr.setup_session_workspace(
        sandbox_id=uuid4(),
        session_id=uuid4(),
        llm_config=_LLM_CONFIG,
        nextjs_port=None,
        connectable_apps_section="",
    )
    return captured


def test_setup_succeeds_with_sentinel_and_passes_exec_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _run_setup(
        monkeypatch, f"setup output\n{WORKSPACE_SETUP_COMPLETE_SENTINEL}\n"
    )
    assert captured.kwargs["_request_timeout"] == WORKSPACE_SETUP_DEADLINE_SECONDS


def test_setup_raises_when_output_lacks_sentinel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Truncated-at-timeout and failed-partway execs look identical: buffered
    # output with no sentinel.
    with pytest.raises(RuntimeError, match="did not complete"):
        _run_setup(monkeypatch, "Copying outputs template\nbun install ...")
