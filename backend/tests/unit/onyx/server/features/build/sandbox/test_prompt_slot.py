"""Tests for ``KubernetesSandboxManager.prompt_slot``.

Empirical finding (E2E chaos test, 2026-05-23): opencode-serve's
``prompt_async`` is fire-and-forget and not concurrent-safe. A second
POST against a busy session returns 2xx but is silently dropped; the
second subscriber's bus catches the *first* turn's terminator and emits
PromptResponse as if turn 2 succeeded, while a phantom user_message gets
persisted with no assistant reply.

The fix: a per-(sandbox_id, opencode_session_id) lock, acquired non-
blocking before user_message persistence. These tests lock the contract.

Bypasses ``_initialize`` (no K8s config needed) — pure lock logic.
"""

from __future__ import annotations

import threading
from uuid import UUID
from uuid import uuid4

import pytest

import onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager as ksm
from onyx.server.features.build.configs import AgentTransport
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)


@pytest.fixture(autouse=True)
def _serve_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    """The lock is a no-op outside SERVE mode — force it on for these tests."""
    monkeypatch.setattr(ksm, "AGENT_TRANSPORT", AgentTransport.SERVE)


@pytest.fixture
def mgr() -> KubernetesSandboxManager:
    """KubernetesSandboxManager with just the prompt-lock state populated —
    skips _initialize so no kube config is required."""
    m: KubernetesSandboxManager = object.__new__(KubernetesSandboxManager)
    m._prompt_locks = {}  # type: ignore[attr-defined]
    m._prompt_locks_meta = threading.Lock()  # type: ignore[attr-defined]
    return m


_SBX: UUID = uuid4()
_SES = "ses_test_concurrent"


def test_prompt_slot_first_call_acquires(mgr: KubernetesSandboxManager) -> None:
    """A fresh lock on a never-seen session must be acquirable."""
    with mgr.prompt_slot(_SBX, _SES) as acquired:
        assert acquired is True


def test_prompt_slot_rejects_second_concurrent_acquire(
    mgr: KubernetesSandboxManager,
) -> None:
    """The load-bearing invariant: while one turn holds the slot,
    a second concurrent acquire MUST return False non-blocking. This is
    what prevents the phantom-user_message bug."""
    with mgr.prompt_slot(_SBX, _SES) as outer:
        assert outer is True
        with mgr.prompt_slot(_SBX, _SES) as inner:
            assert inner is False, (
                "second concurrent acquire on the same session must return False"
            )


def test_prompt_slot_releases_on_exit(mgr: KubernetesSandboxManager) -> None:
    """After the first turn finishes (context exits), the next turn must
    be able to acquire — the lock must be properly released."""
    with mgr.prompt_slot(_SBX, _SES) as first:
        assert first is True
    # First context exited; second acquire should now succeed.
    with mgr.prompt_slot(_SBX, _SES) as second:
        assert second is True


def test_prompt_slot_releases_on_exception(mgr: KubernetesSandboxManager) -> None:
    """If the turn raises, the lock MUST still be released — otherwise a
    single bad turn would permanently block the session."""
    with pytest.raises(RuntimeError, match="simulated"):
        with mgr.prompt_slot(_SBX, _SES) as acquired:
            assert acquired is True
            raise RuntimeError("simulated turn failure")
    # Lock released — next acquire succeeds.
    with mgr.prompt_slot(_SBX, _SES) as after:
        assert after is True


def test_prompt_slot_different_sessions_dont_block(
    mgr: KubernetesSandboxManager,
) -> None:
    """The lock keys on (sandbox_id, opencode_session_id) — two
    DIFFERENT sessions on the same sandbox must NOT serialize. Otherwise
    two users sharing one sandbox couldn't both have active turns."""
    other_session = "ses_test_concurrent_other"
    with mgr.prompt_slot(_SBX, _SES) as first:
        assert first is True
        with mgr.prompt_slot(_SBX, other_session) as second:
            assert second is True


def test_prompt_slot_different_sandboxes_dont_block(
    mgr: KubernetesSandboxManager,
) -> None:
    """Same opencode_session_id collision across two different sandboxes
    is theoretically possible (opencode ids aren't globally unique) —
    serializing across sandboxes would be wrong."""
    other_sandbox = uuid4()
    with mgr.prompt_slot(_SBX, _SES) as first:
        assert first is True
        with mgr.prompt_slot(other_sandbox, _SES) as second:
            assert second is True


def test_prompt_slot_yields_true_when_not_in_serve_mode(
    mgr: KubernetesSandboxManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Outside SERVE mode (i.e., ACP transport), the slot is a no-op —
    it should always yield True without touching the lock dict, because
    each ACP call exec's its own opencode process and can't race."""
    monkeypatch.setattr(ksm, "AGENT_TRANSPORT", AgentTransport.ACP)
    # Two concurrent acquires on the same session both succeed — no lock.
    with mgr.prompt_slot(_SBX, _SES) as first:
        assert first is True
        with mgr.prompt_slot(_SBX, _SES) as second:
            assert second is True
