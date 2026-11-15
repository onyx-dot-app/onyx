"""Synchronous ownership checks reject expired leases and retry transient cache failures."""

import threading
from contextlib import nullcontext
from typing import Any, Literal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from onyx.agents.models import (
    AgentCompletion,
    ExecutionStatus,
    RunProgress,
    RunState,
    RunStatus,
    StepRecord,
    ToolExecutionRecord,
)
from onyx.agents.runtime import Run
from onyx.cache.interface import CacheBackend
from onyx.chat import run_store
from onyx.chat.models import (
    AgentResultState,
    ChatBranch,
    ChatResponseSnapshot,
    ResponseOwner,
)
from onyx.chat.run_store import ChatRunStore, _OwnedRun, _OwnerLease
from onyx.db.models import User
from onyx.llm.models import AssistantMessage, ToolResultMessage
from onyx.llm.models import ToolCall as ModelToolCall


class Clock:
    now = 0.0

    def monotonic(self) -> float:
        return self.now


@pytest.fixture
def ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ChatRunStore, _OwnerLease, MagicMock, MagicMock, Clock]:
    clock = Clock()
    monkeypatch.setattr(run_store, "time", clock)
    cache = MagicMock(spec=CacheBackend)
    cache.exists.return_value = False
    cache.get.return_value = None
    cache.renew_if_value.return_value = True
    store = ChatRunStore(
        tenant_id="tenant",
        chat_session_id=uuid4(),
        response_id=1,
        visible_response_ids=[],
        cache=cache,
        follow_up_steps=4,
        user=User(),
        control_cache=cache,
    )
    lease = _OwnerLease(ResponseOwner(token=uuid4(), root_message_id=1))
    run = MagicMock(spec=Run)
    store._leases[1] = lease
    store._owned[1] = _OwnedRun(run, lease)
    return store, lease, run, cache, clock


def test_transient_renewal_failure_retries_without_cancelling(
    ownership: tuple[ChatRunStore, _OwnerLease, MagicMock, MagicMock, Clock],
) -> None:
    store, lease, run, cache, clock = ownership
    cache.renew_if_value.side_effect = [ConnectionError("offline"), True]
    clock.now = 10
    store.poll_control()
    assert lease.error is None
    clock.now = 10.5
    store.poll_control()
    assert cache.renew_if_value.call_count == 1
    clock.now = 11
    store.poll_control()
    assert lease.refreshed == 11
    run.cancel.assert_not_called()


def test_confirmed_ownership_loss_cancels_without_retry(
    ownership: tuple[ChatRunStore, _OwnerLease, MagicMock, MagicMock, Clock],
) -> None:
    store, lease, run, cache, clock = ownership
    cache.renew_if_value.return_value = False
    clock.now = 10
    store.poll_control()
    assert lease.error is not None
    run.cancel.assert_called_once()
    assert cache.renew_if_value.call_count == 1


@pytest.mark.parametrize("operation", ["renewal", "stop"])
def test_slow_cache_response_cannot_revive_expired_ownership(
    ownership: tuple[ChatRunStore, _OwnerLease, MagicMock, MagicMock, Clock],
    operation: Literal["renewal", "stop"],
) -> None:
    store, lease, run, cache, clock = ownership

    def renew(_key: str, _value: bytes, _ttl: int) -> bool:
        clock.now = 55
        return True

    def read_stop(_key: str) -> bytes | None:
        clock.now = 55
        return None

    if operation == "renewal":
        cache.renew_if_value.side_effect = renew
        clock.now = 10
    else:
        cache.get.side_effect = read_stop
    store.poll_control()
    assert isinstance(lease.error, TimeoutError)
    assert lease.refreshed == 0
    run.cancel.assert_called_once()
    reads = cache.get.call_count
    renewals = cache.renew_if_value.call_count
    clock.now = 56
    store.poll_control()
    assert lease.refreshed == 0
    assert cache.get.call_count == reads
    assert cache.renew_if_value.call_count == renewals


def test_renewal_ttl_starts_before_response_arrives(
    ownership: tuple[ChatRunStore, _OwnerLease, MagicMock, MagicMock, Clock],
) -> None:
    store, lease, run, cache, clock = ownership

    def renew(_key: str, _value: bytes, _ttl: int) -> bool:
        clock.now = 14
        return True

    cache.renew_if_value.side_effect = renew
    clock.now = 10
    store.poll_control()
    assert lease.refreshed == 10
    run.cancel.assert_not_called()


def test_stop_read_failure_retries_without_invalidating_lease(
    ownership: tuple[ChatRunStore, _OwnerLease, MagicMock, MagicMock, Clock],
) -> None:
    store, lease, run, cache, _ = ownership
    cache.get.side_effect = [ConnectionError("offline"), b"requested", None]
    store.poll_control()
    assert lease.error is None
    run.cancel.assert_not_called()
    store.poll_control()
    run.cancel.assert_called_once()


def test_root_and_child_control_calls_use_the_callers_thread(
    ownership: tuple[ChatRunStore, _OwnerLease, MagicMock, MagicMock, Clock],
) -> None:
    store, _, root, cache, clock = ownership
    child = MagicMock(spec=Run)
    child_lease = _OwnerLease(ResponseOwner(token=uuid4(), root_message_id=1))
    store._leases[2] = child_lease
    store._owned[2] = _OwnedRun(child, child_lease)
    calling_thread = threading.current_thread()
    checks: list[str] = []
    renewals: list[str] = []

    def read_stop(key: str) -> bytes | None:
        assert threading.current_thread() is calling_thread
        checks.append(key)
        return b"requested" if key == run_store._stop_key(2) else None

    def renew(key: str, _value: bytes, _ttl: int) -> bool:
        assert threading.current_thread() is calling_thread
        renewals.append(key)
        return True

    cache.get.side_effect = read_stop
    cache.renew_if_value.side_effect = renew
    clock.now = 10
    store.poll_control()
    assert checks == [run_store._stop_key(1), run_store._stop_key(2)]
    assert renewals == [run_store._owner_key(1), run_store._owner_key(2)]
    root.cancel.assert_not_called()
    child.cancel.assert_called_once()


def test_saved_child_tool_calls_keep_their_tool_id_and_display_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = MagicMock(spec=CacheBackend)
    name = "mcp__3__my__srv__create_issue"
    store = ChatRunStore(
        tenant_id="tenant",
        chat_session_id=uuid4(),
        response_id=1,
        visible_response_ids=[],
        cache=cache,
        follow_up_steps=4,
        control_cache=cache,
        user=User(),
        tool_ids={name: 7},
    )
    call = ModelToolCall(id="call", name=name, arguments={})
    snapshot = RunState(
        run_id="2",
        agent_id="child",
        parent_run_id="1",
        status=RunStatus.COMPLETE,
        steps=[
            StepRecord(
                message=AssistantMessage(id="2:0", content=[call]),
                generation_status=ExecutionStatus.COMPLETE,
                tools={
                    call.id: ToolExecutionRecord(
                        status=ExecutionStatus.COMPLETE,
                        result=ToolResultMessage(
                            tool_call_id=call.id, tool_name=name, content="created"
                        ),
                        display_name="create_issue",
                    )
                },
            )
        ],
    )
    projected: list[ChatResponseSnapshot] = []
    project = run_store.project_response

    def capture(*args: Any, **kwargs: Any) -> ChatResponseSnapshot:
        projected.append(project(*args, **kwargs))
        raise RuntimeError("projected")

    monkeypatch.setattr(run_store, "project_response", capture)
    lease = _OwnerLease(ResponseOwner(token=uuid4(), root_message_id=1))
    run = MagicMock(spec=Run)
    run.id = "2"
    with pytest.raises(RuntimeError, match="projected"):
        store._save_output(_OwnedRun(run, lease), snapshot)
    [display] = projected
    assert [info.tool_id for info in display.tool_calls] == [7]
    assert display.response is not None
    assert display.response.steps[0].tools[call.id].display_name == "create_issue"


@pytest.mark.parametrize("final_step", [False, True])
def test_every_step_receives_a_bounded_number_of_child_results(
    monkeypatch: pytest.MonkeyPatch, final_step: bool
) -> None:
    cache = MagicMock(spec=CacheBackend)
    chat_id = uuid4()
    store = ChatRunStore(
        tenant_id="tenant",
        chat_session_id=chat_id,
        response_id=1,
        visible_response_ids=[],
        cache=cache,
        follow_up_steps=4,
        control_cache=cache,
        user=User(),
    )
    finished = [
        AgentResultState(
            recipient_id=chat_id,
            agent_id=chat_id,
            response_id=index,
            root_response_id=1,
            status=RunStatus.COMPLETE,
        )
        for index in range(2, 2 + run_store.MAX_AGENT_COMPLETIONS_PER_STEP + 1)
    ]
    monkeypatch.setattr(
        run_store, "get_session_with_tenant", lambda **_: nullcontext(MagicMock())
    )
    monkeypatch.setattr(run_store, "read_run_inputs", lambda *_, **__: ([], finished))
    monkeypatch.setattr(
        run_store,
        "read_agent_completions",
        lambda _session, ids: [
            AgentCompletion(
                agent_id="child",
                agent_path="/root/child",
                run_id=str(response_id),
                status=RunStatus.COMPLETE,
            )
            for response_id in ids
        ],
    )
    run = Run.from_snapshot(
        RunState(
            run_id="1",
            agent_id="parent",
            status=RunStatus.COMPLETE,
            progress=RunProgress(
                step_index=3 if final_step else 2,
                step_limit=4,
                tool_configuration_digest="",
            ),
        )
    )

    received = store.receive_inputs(run)

    # The final step is bounded too; the run reads the rest in later steps.
    assert len(received) == run_store.MAX_AGENT_COMPLETIONS_PER_STEP


def test_the_agent_cap_counts_runs_of_a_later_turn_on_the_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = MagicMock(spec=CacheBackend)
    chat_id = uuid4()
    store = ChatRunStore(
        tenant_id="tenant",
        chat_session_id=chat_id,
        response_id=1,
        visible_response_ids=[1],
        cache=cache,
        follow_up_steps=4,
        control_cache=cache,
        user=User(),
    )
    later = ChatBranch(chat_session_id=chat_id, message_ids=[3, 1])
    counted: list[list[int]] = []

    def active(_session: object, message_ids: list[int]) -> list[int]:
        counted.append(list(message_ids))
        return list(range(run_store.MAX_RUNNING_AGENTS))

    monkeypatch.setattr(run_store, "lock_agent", lambda *_: None)
    monkeypatch.setattr(
        run_store, "get_selected_branch", lambda *_: (MagicMock(), later)
    )
    monkeypatch.setattr(run_store, "active_agent_response_ids", active)

    assert not store._lock_background_capacity(MagicMock())
    assert counted == [[3, 1]]
