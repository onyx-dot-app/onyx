"""Optional, caller-owned agent discovery and execution coordination."""

import math
import threading
import time
from collections.abc import Callable, Collection, Sequence
from concurrent.futures import Future
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from typing import Literal, Protocol, overload
from uuid import UUID, uuid4

from pydantic import BaseModel

from onyx.agents.concurrency import (
    OPERATION_TIMEOUT_SECONDS,
    ExecutionWork,
    wait_operation,
)
from onyx.agents.models import (
    AgentCompletion,
    AgentInfo,
    AgentMessageReceipt,
    AgentMessageRequest,
    AgentMessageStatus,
    AgentResultDetails,
    BackgroundDelegation,
    InputMessageMetadata,
    InputSource,
    MessageDelivery,
    RunAction,
    RunFailure,
    RunFailureKind,
    RunResult,
    RunState,
    RunStatus,
    StepRecord,
)
from onyx.agents.runtime import (
    Agent,
    Run,
    RunFailed,
    RunNotTransferable,
    result_from_snapshot,
    validate_run_completion,
)
from onyx.agents.tools import (
    DEFAULT_AGENT_WAIT_SECONDS,
    AgentControl,
    AgentLifetime,
    ChildRunCancelled,
    SpawnResult,
)
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.models import Message, UserMessage
from onyx.utils.logger import setup_logger

logger = setup_logger()

MAX_LOADED_AGENTS = 64
MAX_CHILD_DEPTH = 8
REMOTE_POLL_SECONDS = 1.0
CHILD_TERMINAL_TIMEOUT_SECONDS = 18.0
MAX_AGENT_COMPLETIONS_PER_STEP = 8


def _agent_completion(info: AgentInfo, state: RunState) -> AgentCompletion:
    output_index = (
        state.answer_step_index
        if state.answer_step_index is not None
        else len(state.steps) - 1
    )
    output = state.steps[output_index].message if state.steps else None
    return AgentCompletion(
        agent_id=info.id,
        agent_path=info.path,
        run_id=state.run_id,
        status=state.status,
        output=output.model_copy(deep=True) if output is not None else None,
        failure=state.failure.model_copy(deep=True)
        if state.failure is not None
        else None,
    )


class RunStore(Protocol):
    """Save terminal output before completion becomes visible to dependent runs."""

    def save(self, run: Run) -> None: ...


class RunOwnership(Protocol):
    """Reserve execution until workers drain, or undo a failed start."""

    def reserve_run_id(
        self,
        *,
        agent: AgentInfo,
        messages: Sequence[Message],
        previous_run_id: str | None,
        parent_run_id: str | None,
        parent_message_id: str | None,
        parent_tool_call_id: str | None,
    ) -> str: ...

    def register(self, run: Run) -> None: ...

    def release(self, run_id: str) -> None: ...

    def abort_start(self, run_id: str) -> None: ...

    def receive_inputs(self, run: Run) -> list[UserMessage]: ...

    def accept_inputs(self, run: Run, step: StepRecord) -> bool:
        """Persist the proposed step, or return false if input removal won."""
        ...

    def close_inputs(self, run: Run, *, can_continue: bool) -> bool:
        """Return unread steering; close admission unless another step can receive it."""
        ...


class AgentDirectory(Protocol):
    """Authorize agent lookup, restoration, and run control within one branch."""

    def list_agents(self) -> list[AgentInfo]:
        """Read branch-visible metadata, including the ancestors of listed agents."""
        ...

    def completed_agents(
        self, parent_id: str, received_run_ids: Collection[str], *, limit: int
    ) -> list[AgentCompletion]:
        """Read unread direct-child completions from this authorized branch."""
        ...

    def lookup_agent(self, agent_id: str, parent_id: str) -> AgentInfo | None: ...

    def restore_agent(self, agent_id: str, parent_id: str) -> Agent: ...

    def read_run(self, run_id: str, parent_id: str) -> RunState | None: ...

    def read_run_status(self, run_id: str, parent_id: str) -> RunStatus: ...

    def cancel_run(self, run_id: str, parent_id: str) -> None: ...

    def resolve_delegation_messages(
        self, parent_run_id: str, delegations: Sequence[BackgroundDelegation]
    ) -> dict[str, str | None]:
        """Map instructions to accepted runs; None is pending, absent means withdrawn."""
        ...

    def submit_message(self, request: AgentMessageRequest) -> AgentMessageReceipt: ...


class _QueuedMessage:
    def __init__(self, request: AgentMessageRequest) -> None:
        self.request = request
        self.target_run_id: str | None = None
        self.starting = False


class _LoadedAgent:
    def __init__(self, agent: Agent, view_id: UUID) -> None:
        self.agent = agent
        self.view_id = view_id


class _TrackedRun:
    """Keep execution ownership and completion tracking together across handoff."""

    def __init__(self) -> None:
        self.execution: Run | None = None
        self.coordination: RunCoordination | None = None
        self.completion: Future[RunState] = Future()
        self.completion.set_running_or_notify_cancel()
        self.cleanup: list[Future[None]] = []
        self.observer_stop: threading.Event | None = None
        self.restored_from_history = False
        self.notification_parent_id: str | None = None


class _CoordinatorState:
    """Execution ownership shared by coordinators with different branch access."""

    def __init__(self) -> None:
        # Shared identity metadata supports ancestry and saved response projection.
        self.registrations: dict[str, AgentInfo] = {}
        self.agents: dict[str, _LoadedAgent] = {}
        self.tracked_runs: dict[str, _TrackedRun] = {}
        # Latest locally executed or released run, independent of archived history reads.
        self.latest: dict[str, RunState] = {}
        self.work = ExecutionWork()
        self.closed = False
        self.lock = threading.RLock()
        self.pending_messages: dict[str, _QueuedMessage] = {}


class AgentCoordinator:
    """Coordinate local executions and access saved agents within an authorized branch."""

    def __init__(
        self,
        *,
        directory: AgentDirectory | None = None,
        store: RunStore | None = None,
        ownership: RunOwnership | None = None,
    ) -> None:
        self._state = _CoordinatorState()
        self._view_id = uuid4()
        # Each branch retains its own authorized identities and selected latest runs.
        self._visible_agents: dict[str, AgentInfo] = {}
        self._visible_run_ids: set[str] = set()
        self._directory = directory
        self._store = store
        self._ownership = ownership

    def view(
        self,
        *,
        directory: AgentDirectory | None = None,
        visible_run_ids: Sequence[str] = (),
        store: RunStore | None = None,
        ownership: RunOwnership | None = None,
    ) -> "AgentCoordinator":
        """Share execution state; inherit each dependency unless its replacement is supplied."""
        self.check_open()
        view = AgentCoordinator(
            directory=directory if directory is not None else self._directory,
            store=store if store is not None else self._store,
            ownership=ownership if ownership is not None else self._ownership,
        )
        view._state = self._state
        with self._state.lock:
            if directory is None:
                view._visible_agents.update(self._visible_agents)
                view._visible_run_ids.update(self._visible_run_ids)
                view._view_id = self._view_id
            view._visible_run_ids.update(visible_run_ids)
        return view

    def run(self, run_id: str) -> Run:
        """Return a locally retained execution or completed result."""
        with self._state.lock:
            tracked = self._state.tracked_runs.get(run_id)
            run = tracked.execution if tracked is not None else None
        if run is None:
            raise ValueError("Run is not owned by this coordinator")
        return run

    def bind_agent(self, agent: Agent) -> None:
        """Keep the current child implementation after a physical owner change."""
        with self._state.lock:
            info = self._state.registrations[agent.id]
            if info.parent_id is not None:
                self._state.agents[agent.id] = _LoadedAgent(agent, self._view_id)

    def release_execution(self, run: Run) -> None:
        """Forget local execution; dependencies retain only its ID and completion."""
        snapshot = run.snapshot()
        with self._state.lock:
            tracked = self._state.tracked_runs[run.id]
            binding = tracked.coordination
            completion = tracked.completion
        # Reserve the local execution until its ownership cleanup finishes.
        try:
            if binding is not None:
                binding.close(released_run_ids=binding.children)
            if self._ownership is not None:
                self._ownership.release(run.id)
        except BaseException as error:
            completion.set_exception(error)
            raise
        finally:
            with self._state.lock:
                tracked.coordination = None
                tracked.execution = None
                self._state.agents.pop(run.agent_id, None)
                self._state.latest[run.agent_id] = snapshot
                has_waiters = any(
                    run.id in entry.coordination.children
                    for entry in self._state.tracked_runs.values()
                    if entry.coordination is not None
                )
        if has_waiters:
            self.observe_completion(run.id, agent_id=run.agent_id)

    def observe_completion(self, run_id: str, *, agent_id: str) -> None:
        """Resolve a remote dependency from storage without retaining its execution."""
        with self._state.lock:
            if self._state.closed:
                return
            tracked = self._state.tracked_runs[run_id]
            if tracked.execution is not None:
                return
            if tracked.observer_stop is not None:
                return
            if self._directory is None:
                return
            future = tracked.completion
            info = self._state.registrations[agent_id]
            stop = threading.Event()
            tracked.observer_stop = stop
        parent_id = info.parent_id or ""

        def observe() -> None:
            deadline = time.monotonic() + OPERATION_TIMEOUT_SECONDS
            while not stop.is_set() and not future.done():
                try:
                    if self.remote_run_status(run_id, parent_id).is_terminal:
                        directory = self._directory
                        if directory is None:
                            raise ValueError("Remote run storage is unavailable")
                        result = directory.read_run(run_id, parent_id)
                        if (
                            result is None
                            or result.run_id != run_id
                            or result.agent_id != info.id
                            or not result.status.is_terminal
                        ):
                            raise ValueError(
                                "Remote run returned an invalid terminal result"
                            )
                        completion_result = result.model_copy(deep=True)
                        with self._state.lock:
                            if stop.is_set() or future.done():
                                return
                            # Reserve publication before releasing the coordinator lock.
                            stop.set()
                            latest = self._state.latest.get(info.id)
                            if latest is not None and latest.run_id == run_id:
                                self._state.latest[info.id] = result
                        future.set_result(completion_result)
                        return
                except Exception:
                    logger.exception("Could not read remote run result; retrying")
                if time.monotonic() >= deadline:
                    with self._state.lock:
                        if stop.is_set() or future.done():
                            return
                        # A new owner needs a fresh completion once observation expires.
                        stop.set()
                    future.set_exception(
                        TimeoutError("Remote run did not complete in time")
                    )
                    return
                stop.wait(REMOTE_POLL_SECONDS)

        try:
            self._state.work.start(observe)
        except Exception as error:
            with self._state.lock:
                if stop.is_set() or future.done():
                    return
                stop.set()
            logger.exception("Could not start dependency observation")
            future.set_exception(error)

    def cancel_child(self, run_id: str, parent_id: str) -> None:
        run = self.child_run(run_id, parent_id)
        if run is not None:
            run.cancel()
            return
        state = self.read_visible_run(run_id, parent_id)
        if not state.status.is_terminal:
            if self._directory is None:
                raise ValueError("Remote run cancellation is unavailable")
            self._directory.cancel_run(run_id, parent_id)

    def remote_run_status(self, run_id: str, parent_id: str) -> RunStatus:
        if self._directory is not None:
            return self._directory.read_run_status(run_id, parent_id)
        return self.read_visible_run(run_id, parent_id).status

    def restore_completed(self, snapshot: RunState) -> Run:
        """Retain an archived terminal result and notify existing dependency waiters."""
        saved = snapshot.model_copy(deep=True)
        restored = Run.from_snapshot(saved)
        deadline = time.monotonic() + OPERATION_TIMEOUT_SECONDS
        while True:
            with self._state.lock:
                self.check_open()
                if restored.agent_id not in self._state.registrations:
                    raise ValueError("Completed run requires a registered agent")
                tracked = self._state.tracked_runs.get(restored.id)
                if tracked is None:
                    tracked = _TrackedRun()
                    self._state.tracked_runs[restored.id] = tracked
                existing = tracked.execution
                completion = tracked.completion
                observer = tracked.observer_stop
                observer_is_publishing = (
                    existing is None
                    and observer is not None
                    and observer.is_set()
                    and not completion.done()
                )
                if not observer_is_publishing:
                    if existing is not None:
                        break
                    if completion.done():
                        if completion.exception() is not None:
                            completion = Future()
                            completion.set_running_or_notify_cancel()
                            tracked.completion = completion
                        elif completion.result() != saved:
                            raise RuntimeError(
                                "Run identity already has a different completion"
                            )
                    if observer is not None:
                        observer.set()
                    tracked.execution = restored
                    tracked.restored_from_history = True
                    latest = self._state.latest.get(restored.agent_id)
                    if latest is not None and latest.run_id == restored.id:
                        self._state.latest[restored.agent_id] = saved.model_copy(
                            deep=True
                        )
                    self._visible_run_ids.add(restored.id)
                    break
            # An observer that selected an outcome publishes without the coordinator lock.
            completion.exception(timeout=max(0, deadline - time.monotonic()))
        if existing is not None:
            if not existing.is_done or existing.snapshot() != saved:
                raise RuntimeError("Run identity already has an execution owner")
            return existing
        if not completion.done():
            completion.set_result(saved)
        return restored

    def completion(self, run_id: str) -> Future[RunState]:
        """Complete after persistence; consumers must not mutate the shared result."""
        with self._state.lock:
            tracked = self._state.tracked_runs.get(run_id)
            future = tracked.completion if tracked is not None else None
        if future is None:
            raise ValueError("Run is not owned by this coordinator")
        return future

    def completed_agents(
        self,
        parent_id: str,
        received_run_ids: Collection[str],
        *,
        limit: int = MAX_AGENT_COMPLETIONS_PER_STEP,
    ) -> list[AgentCompletion]:
        """Read saved background results without copying execution histories."""
        self.check_open()
        if self._directory is not None:
            return self._directory.completed_agents(
                parent_id, received_run_ids, limit=limit
            )
        with self._state.lock:
            candidates = [
                tracked.completion
                for run_id, tracked in self._state.tracked_runs.items()
                if tracked.notification_parent_id == parent_id
                and run_id in self._visible_run_ids
                and run_id not in received_run_ids
                and tracked.completion.done()
                and tracked.completion.exception() is None
            ][:limit]
        results: list[AgentCompletion] = []
        for completion in candidates:
            state = completion.result()
            if state.agent_id is None or not state.status.is_terminal:
                raise ValueError("Agent completion has no terminal identity")
            with self._state.lock:
                info = self._state.registrations[state.agent_id]
            results.append(_agent_completion(info, state))
        return results

    def receive_inputs(self, run: Run) -> list[UserMessage]:
        messages = (
            self._ownership.receive_inputs(run) if self._ownership is not None else []
        )
        completions: list[AgentCompletion] = []
        received = set(run.received_agent_run_ids)
        with run.execution_lock:
            required = [
                item.run_id
                for item in run._progress.background_delegations
                if item.run_id is not None and item.run_id not in received
            ]
        for run_id in dict.fromkeys(required):
            completion = self.child_completion(run_id, run.agent_id)
            if not completion.done():
                continue
            state = completion.result()
            if state.agent_id is None:
                raise ValueError("Completed delegation has no agent identity")
            info = self.lookup_agent(state.agent_id, run.agent_id)
            if info is None:
                raise ValueError("Completed delegation is unavailable to its parent")
            completions.append(_agent_completion(info, state))
            received.add(run_id)
        completions.extend(self.completed_agents(run.agent_id, received))
        for completion in completions:
            output = completion.output
            messages.append(
                UserMessage(
                    id=completion.message_id,
                    content=output.text if output is not None else "",
                    metadata=InputMessageMetadata(
                        source=InputSource.AGENT_RESULT,
                        source_run_id=completion.run_id,
                        sender_agent_id=completion.agent_id,
                        result=AgentResultDetails(
                            agent_id=completion.agent_id,
                            agent_path=completion.agent_path,
                            status=completion.status,
                            failure=completion.failure,
                        ),
                        content_metadata=output.metadata
                        if output is not None
                        else None,
                    ),
                )
            )
        return messages

    def accept_inputs(self, run: Run, step: StepRecord) -> bool:
        return (
            self._ownership.accept_inputs(run, step)
            if self._ownership is not None
            else True
        )

    def notify_inputs(self) -> None:
        with self._state.lock:
            runs = [
                tracked.execution
                for tracked in self._state.tracked_runs.values()
                if tracked.execution is not None
            ]
        for run in runs:
            with run.execution_lock:
                progress = run._state.progress
                waiting = (
                    progress is not None
                    and progress.action == RunAction.WAIT_CHILDREN
                    and not run._state.status.is_terminal
                    and any(
                        item.run_id is None for item in progress.background_delegations
                    )
                )
            if waiting:
                run._wake_execution()

    def close_inputs(self, run: Run, *, can_continue: bool) -> bool:
        return (
            self._ownership.close_inputs(run, can_continue=can_continue)
            if self._ownership is not None
            else False
        )

    def submit_message(self, request: AgentMessageRequest) -> AgentMessageReceipt:
        self.check_open()
        if (
            self._directory is None
            and self.lookup_agent(request.agent_id, request.parent_id) is None
        ):
            raise ValueError("Agent is unavailable to this sender")
        request = request.model_copy(
            update={
                "message": request.message.model_copy(
                    update={
                        "metadata": InputMessageMetadata(
                            source=InputSource.AGENT,
                            source_run_id=request.parent_run_id,
                            sender_agent_id=request.parent_id,
                        ),
                    }
                ),
            }
        )
        if self._directory is not None:
            return self._directory.submit_message(request)
        message_id = request.message.id
        if message_id is None:
            raise ValueError("Agent messages require an identity")
        queued = _QueuedMessage(request.model_copy(deep=True))
        queued.starting = True
        with self._state.lock:
            if message_id in self._state.pending_messages:
                raise ValueError("Agent message is already pending")
            self._state.pending_messages[message_id] = queued
        try:
            active = self.active_run(request.agent_id)
            if request.delivery == MessageDelivery.SEND and active is not None:
                if active.send_message(request.message):
                    with self._state.lock:
                        queued.target_run_id = active.id
        except BaseException:
            with self._state.lock:
                self._state.pending_messages.pop(message_id, None)
            raise
        finally:
            with self._state.lock:
                queued.starting = False
        self._advance_messages(request.agent_id)
        with self._state.lock:
            pending = message_id in self._state.pending_messages
        latest = self.active_run(request.agent_id)
        return AgentMessageReceipt(
            id=message_id,
            agent_id=request.agent_id,
            status=AgentMessageStatus.PENDING
            if pending
            else AgentMessageStatus.ACCEPTED,
            run_id=queued.target_run_id or (latest.id if latest is not None else None),
            message=request.message.text,
            delivery=request.delivery,
        )

    def start_message_run(self, request: AgentMessageRequest) -> Run | None:
        """Start one authorized follow-up after the previous owner has drained."""
        with self._state.lock:
            previous = next(
                (
                    tracked.execution
                    for tracked in reversed(self._state.tracked_runs.values())
                    if tracked.execution is not None
                    and tracked.execution.agent_id == request.agent_id
                ),
                None,
            )
        if previous is not None and not previous.wait_for_idle(timeout=0):
            return None
        agent = self.resolve_child(request.agent_id, request.parent_id)
        run = agent.start(
            messages=[request.message],
            max_steps=request.max_steps,
            deadline_at=datetime.now(timezone.utc)
            + timedelta(seconds=request.total_timeout_s)
            if request.total_timeout_s is not None
            else None,
            coordinator=self,
            cancellation=CancellationSignal(),
            parent_run_id=request.parent_run_id,
            parent_message_id=request.parent_message_id,
            parent_tool_call_id=request.parent_tool_call_id,
        )
        with self._state.lock:
            self._state.tracked_runs[run.id].notification_parent_id = request.parent_id
        return run

    def _advance_messages(self, agent_id: str) -> None:
        if self._directory is not None:
            return
        while True:
            active = self.active_run(agent_id)
            if active is not None and not active.wait_for_idle(timeout=0):
                return
            with self._state.lock:
                if self._state.closed:
                    return
                if any(
                    queued.starting and queued.request.agent_id == agent_id
                    for queued in self._state.pending_messages.values()
                ):
                    return
                latest = self._state.latest.get(agent_id)
                eligible = [
                    (message_id, queued)
                    for message_id, queued in self._state.pending_messages.items()
                    if queued.request.agent_id == agent_id
                    and not queued.starting
                    and (
                        (
                            queued.request.delivery == MessageDelivery.SEND
                            and queued.target_run_id is None
                        )
                        or latest is None
                        or latest.status == RunStatus.COMPLETE
                    )
                ]
                if not eligible:
                    return
                message_id, queued = eligible[0]
                queued.starting = True
                previous = (
                    self._state.tracked_runs.get(queued.target_run_id)
                    if queued.target_run_id is not None
                    else None
                )
                previous_run = previous.execution if previous is not None else None
            try:
                run = self.start_message_run(queued.request)
            except BaseException:
                with self._state.lock:
                    queued.starting = False
                raise
            if run is not None:
                with self._state.lock:
                    sender = self._state.tracked_runs.get(queued.request.parent_run_id)
                    sender_run = sender.execution if sender is not None else None
                if sender_run is not None:
                    with sender_run.execution_lock:
                        for item in sender_run._progress.background_delegations:
                            if item.message_id == message_id:
                                item.run_id = run.id
                        waiting = sender_run._progress.action == RunAction.WAIT_CHILDREN
                    if waiting:
                        sender_run._wake_execution()
            if run is not None and previous_run is not None:
                previous_run.cancel_message(message_id)
            with self._state.lock:
                if run is not None:
                    self._state.pending_messages.pop(message_id, None)
                    queued.target_run_id = run.id
                else:
                    queued.starting = False
            self.notify_inputs()
            if run is None or not run.wait_for_idle(timeout=0):
                return

    def on_idle(self, run: Run) -> None:
        """Continue explicitly queued work on the existing completion thread."""
        self._advance_messages(run.agent_id)

    def accepted_messages(self, message_ids: Collection[str]) -> None:
        with self._state.lock:
            for message_id in message_ids:
                self._state.pending_messages.pop(message_id, None)
        self.notify_inputs()

    def child_completion(self, run_id: str, parent_id: str) -> Future[RunState]:
        """Authorize a dependency and use its persisted completion as the result."""
        if self.child_run(run_id, parent_id) is not None:
            return self.completion(run_id)
        snapshot = self.saved_run(run_id, parent_id)
        if snapshot.agent_id is None:
            raise ValueError("Remote run has no agent identity")
        with self._state.lock:
            self.check_open()
            tracked = self._state.tracked_runs.get(run_id)
            future = tracked.completion if tracked is not None else None
            if (
                tracked is not None
                and tracked.execution is None
                and tracked.observer_stop is not None
                and future is not None
                and future.done()
                and future.exception() is not None
            ):
                # Observation failure does not establish the child's final outcome.
                if snapshot.status.is_terminal:
                    future = None
                elif self._directory is not None:
                    tracked.completion = Future()
                    tracked.completion.set_running_or_notify_cancel()
                    tracked.observer_stop = None
                    future = tracked.completion
            if future is None and not snapshot.status.is_terminal:
                tracked = _TrackedRun()
                self._state.tracked_runs[run_id] = tracked
                future = tracked.completion
        if future is None:
            self.restore_completed(snapshot)
            future = self.completion(run_id)
        elif not future.done():
            self.observe_completion(run_id, agent_id=snapshot.agent_id)
        return future

    def add_completion_cleanup(
        self, run_id: str, callback: Callable[[], None]
    ) -> Future[None]:
        """Clean up local resources after completion or release, once workers drain."""
        completion: Future[None] = Future()
        completion.set_running_or_notify_cancel()
        with self._state.lock:
            tracked = self._state.tracked_runs.get(run_id)
            if tracked is None or tracked.execution is None:
                raise ValueError("Run is not owned by this coordinator")
            if tracked.restored_from_history:
                raise ValueError("Physical cleanup requires a locally owned execution")
            run = tracked.execution
            tracked.cleanup.append(completion)

        def start() -> None:
            def clean() -> None:
                try:
                    callback()
                except BaseException as error:
                    logger.error("Agent completion cleanup failed", exc_info=error)
                    completion.set_exception(error)
                else:
                    completion.set_result(None)

            try:
                self._state.work.start(clean)
            except Exception:
                logger.exception(
                    "Cleanup worker could not start; running cleanup on completion"
                )
                clean()

        run.add_done_callback(lambda: run.add_idle_callback(start))
        return completion

    def track_child_work(self, parent: Run, run_ids: Sequence[str]) -> None:
        """Retain local child workers and cleanup without reading remote state."""
        executions: list[Run] = []
        cleanup: list[Future[None]] = []
        with self._state.lock:
            for run_id in run_ids:
                tracked = self._state.tracked_runs.get(run_id)
                if tracked is None:
                    continue
                if tracked.execution is not None:
                    executions.append(tracked.execution)
                cleanup.extend(tracked.cleanup)
        for execution in executions:
            parent.track_child_work(execution)
        for completion in cleanup:
            parent.work.track_operation(completion)

    def complete(self, run: Run) -> None:
        """Save terminal output before resolving child completion."""
        future = self.completion(run.id)
        try:
            if self._store is not None:
                self._store.save(run)
        except BaseException as error:
            future.set_exception(error)
            raise
        else:
            future.set_result(run.snapshot())

    def reserve_run_id(
        self,
        *,
        agent_id: str,
        messages: Sequence[Message],
        previous_run_id: str | None,
        parent_run_id: str | None,
        parent_message_id: str | None,
        parent_tool_call_id: str | None,
    ) -> str:
        if self._ownership is None:
            return str(uuid4())
        with self._state.lock:
            self.check_open()
            info = self._state.registrations.get(agent_id)
            if info is None:
                if parent_run_id is not None:
                    raise ValueError("Child agent is not registered")
                info = AgentInfo(
                    id=agent_id,
                    path="/root",
                    parent_id=None,
                    description="",
                    restoration_config=None,
                )
        return self._ownership.reserve_run_id(
            agent=info,
            messages=messages,
            previous_run_id=previous_run_id,
            parent_run_id=parent_run_id,
            parent_message_id=parent_message_id,
            parent_tool_call_id=parent_tool_call_id,
        )

    def begin(self, run: Run) -> None:
        if self._ownership is not None:
            self._ownership.register(run)

    def abort_start(self, run_id: str) -> None:
        if self._ownership is not None:
            self._ownership.abort_start(run_id)

    def finish(self, run: Run) -> None:
        """Release execution ownership after terminal output is saved."""
        try:
            if self._ownership is not None:
                self._ownership.release(run.id)
        finally:
            self.release(run)

    def register(self, info: AgentInfo) -> None:
        with self._state.lock:
            self.check_open()
            existing = self._state.registrations.get(info.id)
            if existing is not None and existing.parent_id != info.parent_id:
                raise ValueError("Agent registration changes its parent")
            registered = info.model_copy(
                update={"pending_messages": [], "queue_paused": False}
            ).model_copy(deep=True)
            self._state.registrations[info.id] = registered
            self._visible_agents[info.id] = registered

    def registration(self, agent_id: str) -> AgentInfo | None:
        with self._state.lock:
            info = self._state.registrations.get(agent_id)
            return info.model_copy(deep=True) if info is not None else None

    def registrations(self) -> list[AgentInfo]:
        with self._state.lock:
            return [
                info.model_copy(deep=True)
                for info in self._state.registrations.values()
            ]

    def discover_children(self, parent_id: str) -> list[AgentInfo]:
        listed = (
            {info.id: info for info in self._directory.list_agents()}
            if self._directory is not None
            else {}
        )
        for info in listed.values():
            self.register(info)
        with self._state.lock:
            children: dict[str, list[str]] = {}
            for info in self._visible_agents.values():
                if info.parent_id is not None:
                    children.setdefault(info.parent_id, []).append(info.id)
        descendants: list[str] = []
        pending = list(children.get(parent_id, []))
        visited = {parent_id}
        while pending:
            agent_id = pending.pop()
            if agent_id in visited:
                raise ValueError("Agent hierarchy contains a cycle")
            visited.add(agent_id)
            descendants.append(agent_id)
            pending.extend(children.get(agent_id, []))
        discovered: list[AgentInfo] = []
        for agent_id in descendants:
            if agent_id in listed:
                discovered.append(
                    self._refresh_agent_info(
                        listed[agent_id], parent_id, authoritative=True
                    )
                )
            elif (info := self.lookup_agent(agent_id, parent_id)) is not None:
                discovered.append(info)
        return discovered

    def _current_info(
        self, agent_id: str, parent_id: str
    ) -> tuple[AgentInfo | None, bool]:
        if self._directory is not None:
            info = self._directory.lookup_agent(agent_id, parent_id)
            if info is not None:
                if info.id != agent_id:
                    raise ValueError("Archive returned a different agent")
                self.register(info)
                return info, True
        return self._lookup(agent_id, parent_id), False

    def lookup_agent(self, agent_id: str, parent_id: str) -> AgentInfo | None:
        """Read one visible descendant and refresh its latest execution status."""
        info, authoritative = self._current_info(agent_id, parent_id)
        if info is None:
            return None
        return self._refresh_agent_info(info, parent_id, authoritative=authoritative)

    def _refresh_agent_info(
        self, info: AgentInfo, parent_id: str, *, authoritative: bool
    ) -> AgentInfo:
        agent_id = info.id
        # Run locks must be acquired outside the coordinator lock.
        with self._state.lock:
            active = next(
                (
                    tracked.coordination.run
                    for tracked in self._state.tracked_runs.values()
                    if tracked.coordination is not None
                    and tracked.coordination.run.agent_id == agent_id
                ),
                None,
            )
            saved = self._state.latest.get(agent_id)
            active_visible = active is not None and active.id in self._visible_run_ids
            saved_visible = saved is not None and saved.run_id in self._visible_run_ids
            if authoritative:
                active_visible = (
                    active_visible
                    and active is not None
                    and active.id == info.latest_run_id
                )
                saved_visible = (
                    saved_visible
                    and saved is not None
                    and saved.run_id == info.latest_run_id
                )
        if active is not None and active_visible:
            info = info.model_copy(
                update={"latest_run_id": active.id, "status": active.status}
            )
        elif saved is not None and saved_visible:
            info = info.model_copy(
                update={"latest_run_id": saved.run_id, "status": saved.status}
            )
        elif (
            self._directory is not None
            and info.latest_run_id is not None
            and (info.status is None or not info.status.is_terminal)
        ):
            info = info.model_copy(
                update={"status": self.remote_run_status(info.latest_run_id, parent_id)}
            )
        pending = info.pending_messages
        if self._directory is None:
            with self._state.lock:
                pending = [
                    AgentMessageReceipt(
                        id=message_id,
                        agent_id=agent_id,
                        status=AgentMessageStatus.PENDING,
                        run_id=queued.target_run_id,
                        message=queued.request.message.text,
                        delivery=queued.request.delivery,
                    )
                    for message_id, queued in self._state.pending_messages.items()
                    if queued.request.agent_id == agent_id
                ]
        return info.model_copy(
            update={
                "pending_messages": pending,
                "queue_paused": bool(pending)
                and info.status
                in (RunStatus.CANCELLED, RunStatus.ERROR, RunStatus.LIMIT),
            },
        ).model_copy(deep=True)

    def bind(self, run: Run) -> "RunCoordination":
        with self._state.lock:
            if self._state.closed:
                raise RuntimeError("Agent coordination is closed")
            if run.agent_id not in self._state.registrations:
                self.register(
                    AgentInfo(
                        id=run.agent_id,
                        path="/root",
                        parent_id=None,
                        description="",
                        restoration_config=None,
                    )
                )
            if any(
                tracked.coordination.run.agent_id == run.agent_id
                for tracked in self._state.tracked_runs.values()
                if tracked.coordination is not None
            ):
                raise RuntimeError("Agent is already running or draining")
            tracked = self._state.tracked_runs.get(run.id)
            if tracked is not None and tracked.execution is not None:
                raise RuntimeError("Run identity was already used")
            previous = self._state.latest.get(run.agent_id)
            if (
                previous is not None
                and previous.run_id == run.id
                and previous.status.is_terminal
            ):
                raise RuntimeError("Run is already complete")
            binding = RunCoordination(self, run)
            if tracked is None:
                tracked = _TrackedRun()
                self._state.tracked_runs[run.id] = tracked
            tracked.coordination = binding
            tracked.execution = run
            stop = tracked.observer_stop
            if (stop is not None and stop.is_set()) or (
                tracked.completion.done() and tracked.completion.exception() is not None
            ):
                tracked.completion = Future()
                tracked.completion.set_running_or_notify_cancel()
            if stop is not None:
                stop.set()
                tracked.observer_stop = None
            self._visible_run_ids.add(run.id)
        return binding

    def close(self, timeout: float = DEFAULT_AGENT_WAIT_SECONDS) -> bool:
        if not 0 <= timeout <= OPERATION_TIMEOUT_SECONDS:
            raise ValueError("Close timeout is outside its allowed bounds")
        with self._state.lock:
            self._state.closed = True
            for tracked in self._state.tracked_runs.values():
                if tracked.observer_stop is not None:
                    tracked.observer_stop.set()
            bindings = [
                tracked.coordination
                for tracked in self._state.tracked_runs.values()
                if tracked.coordination is not None
            ]
            released_ids = {
                run_id
                for run_id, tracked in self._state.tracked_runs.items()
                if tracked.execution is None
            }
        for binding in bindings:
            binding.close(released_run_ids=released_ids)
            binding.run.cancel()
        with self._state.lock:
            runs = [
                tracked.execution
                for tracked in self._state.tracked_runs.values()
                if tracked.execution is not None
            ]
        deadline = time.monotonic() + timeout
        for run in runs:
            try:
                run.wait_for_completion(timeout=max(0, deadline - time.monotonic()))
            except TimeoutError:
                return False
            try:
                if not run.wait_for_idle(timeout=max(0, deadline - time.monotonic())):
                    return False
            except Exception:
                logger.warning("Agent ownership cleanup failed", exc_info=True)
        with self._state.lock:
            completions = [
                tracked.completion
                for run_id, tracked in self._state.tracked_runs.items()
                if run_id not in released_ids
            ]
            cleanup = [
                future
                for run_id, tracked in self._state.tracked_runs.items()
                if run_id not in released_ids
                for future in tracked.cleanup
            ]
        for completion in completions:
            try:
                completion.result(timeout=max(0, deadline - time.monotonic()))
            except TimeoutError:
                return False
            except Exception:
                logger.warning("Agent completion failed during shutdown", exc_info=True)
        for future in cleanup:
            try:
                future.result(timeout=max(0, deadline - time.monotonic()))
            except TimeoutError:
                return False
            except Exception:
                logger.warning("Agent cleanup failed during shutdown", exc_info=True)
        if not self._state.work.tracker.wait_idle(max(0, deadline - time.monotonic())):
            return False
        with self._state.lock:
            self._state.agents.clear()
            for tracked in self._state.tracked_runs.values():
                tracked.coordination = None
            self._state.latest.clear()
        return True

    @property
    def is_closed(self) -> bool:
        with self._state.lock:
            return self._state.closed

    def check_open(self) -> None:
        with self._state.lock:
            if self._state.closed:
                raise RuntimeError("Agent coordination is closed")

    def register_child(
        self,
        agent: Agent,
        *,
        parent_id: str,
        name: str,
        description: str,
        restoration_config: BaseModel | None,
    ) -> AgentInfo:
        if not name or "/" in name:
            raise ValueError("Agent name must be a nonempty label without slashes")
        with self._state.lock:
            self.check_open()
            parent = self._state.registrations[parent_id]
            ancestor = parent
            depth = 0
            while ancestor.parent_id is not None:
                depth += 1
                ancestor = self._state.registrations[ancestor.parent_id]
            if depth >= MAX_CHILD_DEPTH:
                raise ValueError("Agent nesting limit exceeded")
            if (
                agent.id in self._state.registrations
                or len(self._state.agents) >= MAX_LOADED_AGENTS
            ):
                raise ValueError(
                    "Agent already registered or loaded agent limit exceeded"
                )
            info = AgentInfo(
                id=agent.id,
                path=f"{parent.path}/{name}",
                parent_id=parent_id,
                description=description,
                restoration_config=restoration_config,
            )
            registered = info.model_copy(
                update={"pending_messages": [], "queue_paused": False}
            ).model_copy(deep=True)
            self._state.registrations[agent.id] = registered
            self._visible_agents[agent.id] = registered
            self._state.agents[agent.id] = _LoadedAgent(agent, self._view_id)
            return info

    def unregister_child(self, agent_id: str) -> None:
        with self._state.lock:
            self._state.agents.pop(agent_id)
            self._state.registrations.pop(agent_id)
            self._visible_agents.pop(agent_id, None)

    def active_run(self, agent_id: str) -> Run | None:
        with self._state.lock:
            return next(
                (
                    tracked.coordination.run
                    for tracked in reversed(self._state.tracked_runs.values())
                    if tracked.coordination is not None
                    and tracked.coordination.run.agent_id == agent_id
                ),
                None,
            )

    def child_run(self, run_id: str, parent_id: str) -> Run | None:
        with self._state.lock:
            tracked = self._state.tracked_runs.get(run_id)
            run = tracked.execution if tracked is not None else None
        if run is None:
            return None
        if self._lookup(run.agent_id, parent_id) is None:
            raise ValueError("Run is not available to this parent")
        with self._state.lock:
            visible = run_id in self._visible_run_ids
        if not visible:
            self.read_visible_run(run_id, parent_id, agent_id=run.agent_id)
        return run

    def release(self, run: Run) -> None:
        with self._state.lock:
            is_child = self._state.registrations[run.agent_id].parent_id is not None
        snapshot = run.snapshot() if is_child else None
        status = snapshot.status if snapshot is not None else run.status
        with self._state.lock:
            tracked = self._state.tracked_runs[run.id]
            tracked.coordination = None
            if status == RunStatus.RUNNING:
                tracked.execution = None
                previous = self._state.latest.get(run.agent_id)
                if previous is None or previous.run_id != run.id:
                    del self._state.tracked_runs[run.id]
            if snapshot is not None and status != RunStatus.RUNNING:
                self._state.latest[run.agent_id] = snapshot
            info = self._visible_agents.get(run.agent_id)
            if info is not None and status != RunStatus.RUNNING:
                self._visible_agents[run.agent_id] = info.model_copy(
                    update={
                        "latest_run_id": run.id,
                        "status": status,
                    }
                )

    def _lookup(self, agent_id: str, parent_id: str) -> AgentInfo | None:
        with self._state.lock:
            info = self._visible_agents.get(agent_id)
            ancestor = info
            visited: set[str] = set()
            while ancestor is not None:
                if ancestor.id in visited or len(visited) > MAX_CHILD_DEPTH:
                    raise ValueError(
                        "Agent hierarchy contains a cycle or exceeds its limit"
                    )
                visited.add(ancestor.id)
                if ancestor.parent_id == parent_id:
                    return info
                if ancestor.parent_id is None:
                    raise ValueError("Agent is not available to this parent")
                ancestor = self._visible_agents.get(ancestor.parent_id)
        if self._directory is not None:
            info = self._directory.lookup_agent(agent_id, parent_id)
            if info is not None:
                if info.id != agent_id:
                    raise ValueError("Archive returned a different agent")
                self.register(info)
            return info
        if info is not None:
            raise ValueError("Agent is not available to this parent")
        return None

    def _cached_agent(
        self, agent_id: str, latest_run_id: str | None, *, check_history: bool
    ) -> Agent | None:
        with self._state.lock:
            loaded = self._state.agents.get(agent_id)
        if loaded is None or loaded.view_id != self._view_id:
            return None
        # Agent.start takes its lock before the coordinator lock.
        if check_history and loaded.agent.latest_run_id != latest_run_id:
            return None
        with self._state.lock:
            return loaded.agent if self._state.agents.get(agent_id) is loaded else None

    def resolve_child(self, agent_id: str, parent_id: str) -> Agent:
        info, authoritative = self._current_info(agent_id, parent_id)
        if info is None:
            raise ValueError("Agent is unavailable to this sender")
        cached = self._cached_agent(
            agent_id, info.latest_run_id, check_history=authoritative
        )
        if cached is not None:
            return cached
        with self._state.lock:
            if (
                agent_id not in self._state.agents
                and len(self._state.agents) >= MAX_LOADED_AGENTS
            ):
                raise ValueError("Loaded agent limit exceeded")
        if self._directory is None:
            raise ValueError("Agent restoration is unavailable")
        restored = self._directory.restore_agent(agent_id, parent_id)
        if restored.id != agent_id:
            raise ValueError("Restoration returned a different agent")
        cached = self._cached_agent(
            agent_id, info.latest_run_id, check_history=authoritative
        )
        if cached is not None:
            return cached
        with self._state.lock:
            self.check_open()
            if any(
                tracked.coordination.run.agent_id == agent_id
                for tracked in self._state.tracked_runs.values()
                if tracked.coordination is not None
            ):
                raise RuntimeError("Agent is already running or draining")
            if (
                agent_id not in self._state.agents
                and len(self._state.agents) >= MAX_LOADED_AGENTS
            ):
                raise ValueError("Loaded agent limit exceeded")
            self._state.agents[agent_id] = _LoadedAgent(restored, self._view_id)
        return restored

    def read_visible_run(
        self, run_id: str, parent_id: str, *, agent_id: str | None = None
    ) -> RunState:
        """Authorize a specific run through this view's selected history."""
        record = (
            self._directory.read_run(run_id, parent_id)
            if self._directory is not None
            else None
        )
        if record is None:
            raise ValueError("Run is not available to this parent")
        if record.run_id != run_id or record.agent_id is None:
            raise ValueError("Archive returned a different run")
        if agent_id is not None and record.agent_id != agent_id:
            raise ValueError("Archive returned a different agent")
        if self._lookup(record.agent_id, parent_id) is None:
            raise ValueError("Run is not available to this parent")
        with self._state.lock:
            self._visible_run_ids.add(run_id)
        return record

    def run_state(self, run_id: str, parent_id: str) -> RunState:
        local = self.child_run(run_id, parent_id)
        if local is not None:
            return local.snapshot()
        return self.saved_run(run_id, parent_id)

    @overload
    def saved_run(
        self, run_id: str, parent_id: str, *, load_archive: Literal[True] = True
    ) -> RunState: ...

    @overload
    def saved_run(
        self, run_id: str, parent_id: str, *, load_archive: Literal[False]
    ) -> RunState | None: ...

    def saved_run(
        self, run_id: str, parent_id: str, *, load_archive: bool = True
    ) -> RunState | None:
        with self._state.lock:
            saved = next(
                (item for item in self._state.latest.values() if item.run_id == run_id),
                None,
            )
            tracked = self._state.tracked_runs.get(run_id)
            completion = tracked.completion if tracked is not None else None
            if (
                saved is None
                and completion is not None
                and completion.done()
                and completion.exception() is None
            ):
                saved = completion.result()
            visible = run_id in self._visible_run_ids
        if saved is not None and visible:
            if (
                saved.agent_id is None
                or self._lookup(saved.agent_id, parent_id) is None
            ):
                raise ValueError("Run is not available to this parent")
            return saved.model_copy(deep=True)
        if not load_archive:
            return None
        return self.read_visible_run(
            run_id, parent_id, agent_id=saved.agent_id if saved is not None else None
        )


class RunCoordination:
    """Track foreground dependencies and cancellation links for one parent execution."""

    def __init__(
        self,
        coordinator: AgentCoordinator,
        run: Run,
    ) -> None:
        self.coordinator = coordinator
        self.run = run
        # Map foreground run IDs to whether their failure was handled by a tool.
        self.children: dict[str, bool] = {}
        self._links = ExitStack()
        self._finished = False
        self._lock = run.execution_lock

    def close(self, *, released_run_ids: Collection[str] = ()) -> None:
        """Close cancellation links and forget dependencies no longer owned locally."""
        with self._lock:
            self._links.close()
            for run_id in tuple(released_run_ids):
                self.children.pop(run_id, None)

    def check_tool_active(self, active: threading.Event) -> None:
        self.run.cancellation_signal.check()
        with self._lock:
            if not active.is_set() or self._finished or not self.run.is_accepting:
                raise RuntimeError("Coordination requires an active tool invocation")
        self.coordinator.check_open()

    def track_cleanup(self, run_id: str, future: Future[None]) -> None:
        with self._lock:
            if self._finished and run_id in self.children:
                self.run.work.track_operation(future)

    def for_tool(
        self, call_id: str, parent_message_id: str, active: threading.Event
    ) -> AgentControl:
        return _ToolControl(self, call_id, parent_message_id, active)

    def start_child(
        self,
        agent: Agent,
        messages: Sequence[Message],
        max_steps: int,
        *,
        call_id: str,
        message_id: str,
        lifetime: AgentLifetime = AgentLifetime.FOREGROUND,
        deadline_at: datetime | None = None,
    ) -> Run:
        run = agent.start(
            messages=messages,
            max_steps=max_steps,
            deadline_at=deadline_at,
            coordinator=self.coordinator,
            cancellation=CancellationSignal(),
            parent_run_id=self.run.id,
            parent_tool_call_id=call_id,
            parent_message_id=message_id,
            _event_parent=self.run.event_delivery
            if lifetime == AgentLifetime.FOREGROUND
            else None,
        )
        if lifetime == AgentLifetime.BACKGROUND:
            with self.coordinator._state.lock:
                self.coordinator._state.tracked_runs[
                    run.id
                ].notification_parent_id = self.run.agent_id
        else:
            with self._lock:
                if self._finished:
                    run.cancel()
                    self.run.track_child_work(run)
                else:
                    self._include_predecessors(run)
                    self._attach(run.id)
        if lifetime == AgentLifetime.BACKGROUND and self.run.parent_run_id is not None:
            with self._lock:
                self.run._progress.background_delegations.append(
                    BackgroundDelegation(agent_id=agent.id, run_id=run.id)
                )
        return run

    def _include_predecessors(self, run: Run) -> None:
        """Retain completed background history consumed by this foreground child."""
        previous_id = run.previous_run_id
        predecessors: list[Run] = []
        seen: set[str] = set()
        while (
            previous_id and previous_id not in self.children and previous_id not in seen
        ):
            seen.add(previous_id)
            previous = self.coordinator.child_run(previous_id, self.run.agent_id)
            if previous is None:
                break
            if previous.parent_run_id != self.run.id or not previous.status.is_terminal:
                break
            predecessors.append(previous)
            previous_id = previous.previous_run_id
        for previous in reversed(predecessors):
            self.children[previous.id] = True

    def _attach(self, run_id: str) -> None:
        self.children[run_id] = False
        self._links.enter_context(
            self.run.cancellation_signal.on_cancel(
                lambda: self.coordinator.cancel_child(run_id, self.run.agent_id)
            )
        )

    def attach_children(self, run_ids: Sequence[str]) -> None:
        """Reconnect authorized foreground dependencies, including remote runs."""
        for run_id in run_ids:
            self.coordinator.child_completion(run_id, self.run.agent_id)
        with self._lock:
            for run_id in run_ids:
                if run_id not in self.children:
                    self._attach(run_id)

    def observe_children(self, run_ids: Sequence[str]) -> None:
        """Mark failures consumed by a successful delegation completion callback."""
        with self._lock:
            for run_id in run_ids:
                if run_id in self.children:
                    self.children[run_id] = True

    def has_unconsumed_delegations(self) -> bool:
        received = self.run.received_agent_run_ids
        with self._lock:
            return any(
                item.run_id not in received
                for item in self.run._progress.background_delegations
            )

    def wait_for_delegations(self) -> bool:
        """Resolve submitted instructions and suspend until their child results are saved."""
        with self._lock:
            messages = {
                item.message_id
                for item in self.run._progress.background_delegations
                if item.message_id is not None and item.run_id is None
            }
        if messages:
            directory = self.coordinator._directory
            if directory is not None:
                with self._lock:
                    unresolved = [
                        item.model_copy()
                        for item in self.run._progress.background_delegations
                        if item.message_id in messages
                    ]
                resolved = directory.resolve_delegation_messages(
                    self.run.id, unresolved
                )
            else:
                with self.coordinator._state.lock:
                    resolved = {
                        message_id: None
                        for message_id in messages
                        if message_id in self.coordinator._state.pending_messages
                    }
                    missing_messages = messages - resolved.keys()
                    tracked_runs = (
                        list(self.coordinator._state.tracked_runs.items())
                        if missing_messages
                        else []
                    )
                for run_id, tracked in tracked_runs:
                    execution = tracked.execution
                    if execution is not None:
                        with execution.execution_lock:
                            state = execution._state
                            accepted = {
                                message.id for message in state.input_messages
                            } | execution.received_input_ids
                    elif (
                        tracked.completion.done()
                        and tracked.completion.exception() is None
                    ):
                        state = tracked.completion.result()
                        accepted = {message.id for message in state.input_messages} | {
                            message.id
                            for step in state.steps
                            for message in step.input_messages
                        }
                    else:
                        continue
                    for message_id in missing_messages & accepted:
                        resolved[message_id] = run_id
            with self._lock:
                retained = []
                for item in self.run._progress.background_delegations:
                    if item.message_id in messages and item.run_id is None:
                        if item.message_id not in resolved:
                            logger.debug(
                                "Delegated instruction %s was withdrawn",
                                item.message_id,
                            )
                            continue
                        item.run_id = resolved[item.message_id]
                    retained.append(item)
                self.run._progress.background_delegations = retained
        received = self.run.received_agent_run_ids
        with self._lock:
            delegations = [
                item.model_copy() for item in self.run._progress.background_delegations
            ]
        pending: list[str] = []
        for item in delegations:
            if item.run_id is None:
                recipient = self.coordinator.lookup_agent(
                    item.agent_id, self.run.agent_id
                )
                if recipient is not None and recipient.queue_paused:
                    raise RunFailed(
                        RunFailure(
                            kind=RunFailureKind.EXECUTION,
                            message="A delegated instruction cannot start because the child agent's queue is paused.",
                        )
                    )
                continue
            if item.run_id in received:
                continue
            completion = self.coordinator.child_completion(
                item.run_id, self.run.agent_id
            )
            if completion.done():
                completion.result()
            else:
                pending.append(item.run_id)
        if pending:
            self.run.watch_children(pending)
        return bool(pending) or any(item.run_id is None for item in delegations)

    def observed_children(self) -> list[str]:
        with self._lock:
            return [run_id for run_id, observed in self.children.items() if observed]

    def pending_children(self) -> list[str]:
        with self._lock:
            return [
                run_id
                for run_id in self.children
                if not self.coordinator.completion(run_id).done()
            ]

    def validate_handoff(self) -> None:
        try:
            self.coordinator.check_open()
        except RuntimeError as error:
            raise RunNotTransferable("Coordinator is closing") from error
        if self.pending_children():
            raise RunNotTransferable(
                "Foreground child runs must finish before parent transfer"
            )

    def finish(self, cancel: bool) -> list[RunState]:
        with self._lock:
            self._finished = True
            child_run_ids = list(self.children)
        deadline = time.monotonic() + (
            CHILD_TERMINAL_TIMEOUT_SECONDS if cancel else OPERATION_TIMEOUT_SECONDS
        )
        failure: RunFailed | None = None
        records: list[RunState] = []
        try:
            self.coordinator.track_child_work(self.run, child_run_ids)
            if cancel:
                cancellation_error: Exception | None = None
                for run_id in child_run_ids:
                    try:
                        self.coordinator.cancel_child(run_id, self.run.agent_id)
                    except Exception as error:
                        logger.exception("Could not cancel child run %s", run_id)
                        if cancellation_error is None:
                            cancellation_error = error
                if cancellation_error is not None:
                    raise cancellation_error
            for run_id in child_run_ids:
                try:
                    future = self.coordinator.completion(run_id)
                    if not cancel:
                        wait_operation(
                            future,
                            self.run.cancellation_signal,
                            max(0, deadline - time.monotonic()),
                        )
                    state = future.result(timeout=max(0, deadline - time.monotonic()))
                    records.append(state.model_copy(deep=True))
                    validate_run_completion(state)
                except RunFailed as error:
                    with self._lock:
                        observed = self.children.get(run_id, False)
                    if not observed and not cancel and failure is None:
                        failure = error
                except AgentCancelled:
                    if not cancel:
                        self.run.cancellation_signal.check()
                    logger.debug("Child execution was cancelled: %s", run_id)
                except TimeoutError as error:
                    try:
                        self.coordinator.cancel_child(run_id, self.run.agent_id)
                    except Exception:
                        logger.exception(
                            "Could not cancel timed-out child run %s", run_id
                        )
                    if not cancel:
                        raise
                    raise TimeoutError(
                        "Child execution did not publish a terminal record after cancellation"
                    ) from error
        finally:
            # Cancelling a suspended child can start a new worker before cleanup.
            self.coordinator.track_child_work(self.run, child_run_ids)
            self._links.close()
        if failure is not None:
            raise failure
        return records

    def completed_child_states(self, run_ids: Sequence[str]) -> list[RunState] | None:
        """Return completed dependencies, or wait; propagate failures from any child."""
        states: list[RunState] = []
        pending = False
        for run_id in run_ids:
            future = self.coordinator.child_completion(run_id, self.run.agent_id)
            if future.done():
                states.append(future.result())
            else:
                pending = True
        if pending:
            return None
        return [state.model_copy(deep=True) for state in states]

    def release(self) -> None:
        self.coordinator.release(self.run)
        with self._lock:
            self.children.clear()


class _ToolControl(AgentControl):
    def __init__(
        self,
        owner: RunCoordination,
        call_id: str,
        message_id: str,
        active: threading.Event,
    ) -> None:
        self.owner = owner
        self.call_id = call_id
        self.message_id = message_id
        self.active = active

    def discover_children(self) -> list[AgentInfo]:
        self.owner.check_tool_active(self.active)
        return self.owner.coordinator.discover_children(self.owner.run.agent_id)

    def lookup_agent(self, agent_id: str) -> AgentInfo | None:
        self.owner.check_tool_active(self.active)
        return self.owner.coordinator.lookup_agent(agent_id, self.owner.run.agent_id)

    def _message(
        self,
        agent_id: str,
        *,
        message: str,
        delivery: Literal[MessageDelivery.SEND, MessageDelivery.QUEUE],
        max_steps: int,
        total_timeout_s: float | None,
    ) -> AgentMessageReceipt:
        self.owner.check_tool_active(self.active)
        if not message.strip():
            raise ValueError("Agent instructions must not be empty")
        if total_timeout_s is not None and not math.isfinite(total_timeout_s):
            raise ValueError("Child timeout must be finite")
        recipient = (
            self.owner.coordinator.lookup_agent(agent_id, self.owner.run.agent_id)
            if self.owner.run.parent_run_id is not None
            else None
        )
        receipt = self.owner.coordinator.submit_message(
            AgentMessageRequest(
                agent_id=agent_id,
                parent_id=self.owner.run.agent_id,
                message=UserMessage(
                    id=str(uuid4()),
                    content=message,
                ),
                delivery=delivery,
                max_steps=max_steps,
                total_timeout_s=total_timeout_s,
                parent_run_id=self.owner.run.id,
                parent_message_id=self.message_id,
                parent_tool_call_id=self.call_id,
            )
        )
        if recipient is not None:
            with self.owner._lock:
                self.owner.run._progress.background_delegations.append(
                    BackgroundDelegation(
                        agent_id=agent_id,
                        message_id=receipt.id,
                        tool_call_id=self.call_id,
                        run_id=receipt.run_id
                        if receipt.status == AgentMessageStatus.ACCEPTED
                        else None,
                    )
                )
        return receipt

    def send_message(
        self,
        agent_id: str,
        *,
        message: str,
        max_steps: int,
        total_timeout_s: float | None = None,
    ) -> AgentMessageReceipt:
        return self._message(
            agent_id,
            message=message,
            delivery=MessageDelivery.SEND,
            max_steps=max_steps,
            total_timeout_s=total_timeout_s,
        )

    def queue_message(
        self,
        agent_id: str,
        *,
        message: str,
        max_steps: int,
        total_timeout_s: float | None = None,
    ) -> AgentMessageReceipt:
        return self._message(
            agent_id,
            message=message,
            delivery=MessageDelivery.QUEUE,
            max_steps=max_steps,
            total_timeout_s=total_timeout_s,
        )

    def spawn_agent(
        self,
        agent: Agent,
        *,
        name: str,
        description: str,
        max_steps: int,
        messages: Sequence[Message],
        restoration_config: BaseModel | None = None,
        total_timeout_s: float | None = None,
        lifetime: AgentLifetime = AgentLifetime.FOREGROUND,
    ) -> SpawnResult:
        self.owner.check_tool_active(self.active)
        if total_timeout_s is not None and (
            not math.isfinite(total_timeout_s) or total_timeout_s <= 0
        ):
            raise ValueError("Child timeout must be positive")
        coordinator = self.owner.coordinator
        info = coordinator.register_child(
            agent,
            parent_id=self.owner.run.agent_id,
            name=name,
            description=description,
            restoration_config=restoration_config,
        )
        try:
            run = self.owner.start_child(
                agent,
                messages,
                max_steps,
                call_id=self.call_id,
                message_id=self.message_id,
                lifetime=lifetime,
                deadline_at=datetime.now(timezone.utc)
                + timedelta(seconds=total_timeout_s)
                if total_timeout_s is not None
                else None,
            )
        except BaseException:
            coordinator.unregister_child(agent.id)
            raise
        return SpawnResult(agent_id=agent.id, agent_path=info.path, run_id=run.id)

    def start_run(
        self,
        agent_id: str,
        *,
        max_steps: int,
        messages: Sequence[Message],
        lifetime: AgentLifetime = AgentLifetime.FOREGROUND,
    ) -> str:
        self.owner.check_tool_active(self.active)
        coordinator = self.owner.coordinator
        agent = coordinator.resolve_child(agent_id, self.owner.run.agent_id)
        self.owner.check_tool_active(self.active)
        previous = coordinator.active_run(agent_id)
        if previous is not None and previous.status.is_terminal:
            previous.wait_until_reusable(self.owner.run.cancellation_signal)
        self.owner.check_tool_active(self.active)
        return self.owner.start_child(
            agent,
            messages,
            max_steps,
            call_id=self.call_id,
            message_id=self.message_id,
            lifetime=lifetime,
        ).id

    def wait_run(
        self, run_id: str, *, timeout: float = DEFAULT_AGENT_WAIT_SECONDS
    ) -> RunResult | None:
        self.owner.check_tool_active(self.active)
        if not 0 <= timeout <= OPERATION_TIMEOUT_SECONDS:
            raise ValueError("Wait timeout is outside its allowed bounds")
        run = self.owner.coordinator.child_run(run_id, self.owner.run.agent_id)
        if run is not None:
            completion = self.owner.coordinator.completion(run_id)
            try:
                state = wait_operation(
                    completion, self.owner.run.cancellation_signal, timeout
                )
            except TimeoutError:
                if completion.done():
                    completion.result()
                return None
            except AgentCancelled as error:
                self.owner.observe_children([run_id])
                self.owner.check_tool_active(self.active)
                raise ChildRunCancelled(f"Child run {run_id} was cancelled") from error
            except RunFailed:
                self.owner.observe_children([run_id])
                raise
            return self._result_from_child(state)
        coordinator = self.owner.coordinator
        latest = coordinator.saved_run(
            run_id, self.owner.run.agent_id, load_archive=False
        )
        if latest is not None and latest.status.is_terminal:
            return self._result_from_child(latest)

        try:
            deadline = time.monotonic() + timeout
            while True:
                self.owner.run.cancellation_signal.check()
                if coordinator.remote_run_status(
                    run_id, self.owner.run.agent_id
                ).is_terminal:
                    state = coordinator.read_visible_run(
                        run_id, self.owner.run.agent_id
                    )
                    return self._result_from_child(state)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.owner.check_tool_active(self.active)
                    return None
                try:
                    wait_operation(
                        Future(),
                        self.owner.run.cancellation_signal,
                        min(REMOTE_POLL_SECONDS, remaining),
                    )
                except TimeoutError:
                    continue

        except TimeoutError:
            return None

    def _result_from_child(self, state: RunState) -> RunResult:
        self.owner.observe_children([state.run_id])
        self.owner.check_tool_active(self.active)
        if state.status == RunStatus.CANCELLED:
            raise ChildRunCancelled(f"Child run {state.run_id} was cancelled")
        return result_from_snapshot(state)

    def cancel_run(self, run_id: str) -> None:
        self.owner.check_tool_active(self.active)
        self.owner.coordinator.cancel_child(run_id, self.owner.run.agent_id)
        self.owner.check_tool_active(self.active)

    def add_completion_cleanup(
        self, run_id: str, callback: Callable[[], None]
    ) -> Future[None]:
        """Retain resource cleanup across child suspension, including cancellation."""
        if not self.active.is_set():
            raise RuntimeError(
                "Cleanup registration requires an active tool invocation"
            )
        run = self.owner.coordinator.child_run(run_id, self.owner.run.agent_id)
        if run is None:
            raise ValueError("Cleanup requires an owned child run")
        future = self.owner.coordinator.add_completion_cleanup(run_id, callback)
        self.owner.track_cleanup(run_id, future)
        return future
