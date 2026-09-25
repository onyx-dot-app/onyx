"""Optional, caller-owned agent discovery and execution coordination."""

import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import Future
from contextlib import ExitStack
from typing import Literal, Protocol, overload
from uuid import UUID, uuid4

from pydantic import BaseModel

from onyx.agents.concurrency import (
    CLEANUP_SECONDS,
    OPERATION_TIMEOUT_SECONDS,
    ExecutionWork,
    wait_operation,
)
from onyx.agents.execution_records import RunStatus
from onyx.agents.models import AgentInfo, RunResult, RunState
from onyx.agents.runtime import (
    Agent,
    Run,
    RunFailed,
    RunNotTransferable,
    result_from_snapshot,
)
from onyx.agents.tools import (
    DEFAULT_AGENT_WAIT_SECONDS,
    AgentControl,
    AgentLifetime,
    SpawnResult,
)
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.models import Message
from onyx.utils.logger import setup_logger

logger = setup_logger()

MAX_LOADED_AGENTS = 64
MAX_CHILD_DEPTH = 8
REMOTE_POLL_SECONDS = 1.0
# Each nested execution can use its cleanup bound before publishing terminal output.
CHILD_TERMINAL_TIMEOUT_SECONDS = CLEANUP_SECONDS * (MAX_CHILD_DEPTH + 1)


class RunStore(Protocol):
    """Save terminal output before completion becomes visible to dependent runs."""

    def save(self, run: Run) -> None: ...


class RunOwnership(Protocol):
    """Reserve execution until workers drain, or undo a failed start."""

    def register(self, run: Run) -> None: ...

    def release(self, run_id: str) -> None: ...

    def abort_start(self, run_id: str) -> None: ...


class AgentDirectory(Protocol):
    """Authorize agent lookup, restoration, and run control within one branch."""

    def lookup_agent(self, agent_id: str, parent_id: str) -> AgentInfo | None: ...

    def restore_agent(self, agent_id: str, parent_id: str) -> Agent: ...

    def read_run(self, run_id: str, parent_id: str) -> RunState | None: ...

    def read_run_status(self, run_id: str, parent_id: str) -> RunStatus: ...

    def cancel_run(self, run_id: str, parent_id: str) -> None: ...


class _CoordinatorState:
    """Execution ownership shared by coordinators with different branch access."""

    def __init__(self) -> None:
        # Shared identity metadata supports ancestry and saved response projection.
        self.registrations: dict[str, AgentInfo] = {}
        self.agents: dict[str, Agent] = {}
        self.agent_views: dict[str, UUID] = {}
        self.bindings: dict[str, RunCoordination] = {}
        self.runs: dict[str, Run] = {}
        self.archived_run_ids: set[str] = set()
        self.completions: dict[str, Future[RunState]] = {}
        self.cleanup: dict[str, list[Future[None]]] = {}
        # Latest locally executed or released run, independent of archived history reads.
        self.latest: dict[str, RunState] = {}
        self.work = ExecutionWork()
        self.completion_observers: dict[str, threading.Event] = {}
        self.closed = False
        self.lock = threading.RLock()


class AgentCoordinator:
    """Own agent identities, loaded conversations, and their active or saved runs."""

    def __init__(
        self,
        *,
        agents: Sequence[AgentInfo] = (),
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
        for info in agents:
            if info.id in self._state.registrations:
                raise ValueError("Duplicate agent identity")
            self.register(info)

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
            run = self._state.runs.get(run_id)
        if run is None:
            raise ValueError("Run is not owned by this coordinator")
        return run

    def bind_agent(self, agent: Agent) -> None:
        """Keep the current child implementation after a physical owner change."""
        with self._state.lock:
            info = self._state.registrations[agent.id]
            if info.parent_id is not None:
                self._state.agents[agent.id] = agent
                self._state.agent_views[agent.id] = self._view_id

    def release_execution(self, run: Run) -> None:
        """Forget local execution; dependencies retain only its ID and completion."""
        snapshot = run.snapshot()
        with self._state.lock:
            binding = self._state.bindings.pop(run.id, None)
            self._state.runs.pop(run.id, None)
            self._state.agents.pop(run.agent_id, None)
            self._state.agent_views.pop(run.agent_id, None)
            self._state.latest[run.agent_id] = snapshot
            has_waiters = any(
                run.id in owner.children for owner in self._state.bindings.values()
            )
        if binding is not None:
            binding._links.close()
            binding.children.clear()
        if has_waiters:
            self.observe_completion(run.id)

    def observe_completion(self, run_id: str) -> None:
        """Resolve a released dependency from storage without retaining its execution."""
        with self._state.lock:
            if self._state.closed or run_id in self._state.runs:
                return
            if run_id in self._state.completion_observers:
                return
            if self._directory is None:
                return
            future = self._state.completions[run_id]
            snapshot = next(
                state for state in self._state.latest.values() if state.run_id == run_id
            )
            if snapshot.agent_id is None:
                raise ValueError("Released run has no agent identity")
            info = self._state.registrations[snapshot.agent_id]
            stop = threading.Event()
            self._state.completion_observers[run_id] = stop
        parent_id = info.parent_id or ""

        def observe() -> None:
            deadline = time.monotonic() + OPERATION_TIMEOUT_SECONDS
            while not stop.is_set() and not future.done():
                try:
                    if self._remote_status(run_id, parent_id).is_terminal:
                        directory = self._directory
                        if directory is None:
                            raise ValueError("Released run storage is unavailable")
                        result = directory.read_run(run_id, parent_id)
                        if (
                            result is None
                            or result.run_id != run_id
                            or result.agent_id != info.id
                            or not result.status.is_terminal
                        ):
                            raise ValueError(
                                "Released run returned an invalid terminal result"
                            )
                        with self._state.lock:
                            if stop.is_set():
                                return
                            self._state.latest[info.id] = result
                        future.set_result(result)
                        return
                except Exception:
                    logger.exception("Could not read released run result; retrying")
                if time.monotonic() >= deadline:
                    future.set_exception(
                        TimeoutError("Released run did not complete in time")
                    )
                    return
                stop.wait(REMOTE_POLL_SECONDS)

        try:
            self._state.work.start(observe)
        except Exception as error:
            with self._state.lock:
                self._state.completion_observers.pop(run_id, None)
            logger.exception("Could not start dependency observation")
            future.set_exception(error)

    def cancel_child(self, run_id: str, parent_id: str) -> None:
        run = self.child_run(run_id, parent_id)
        if run is not None:
            run.cancel()
            return
        state = self._read_visible_run(run_id, parent_id)
        if not state.status.is_terminal:
            if self._directory is None:
                raise ValueError("Remote run cancellation is unavailable")
            self._directory.cancel_run(run_id, parent_id)

    def _remote_status(self, run_id: str, parent_id: str) -> RunStatus:
        if self._directory is not None:
            return self._directory.read_run_status(run_id, parent_id)
        return self._read_visible_run(run_id, parent_id).status

    def restore_completed(self, snapshot: RunState) -> Run:
        """Retain an archived terminal result without executing or saving it again."""
        restored = Run.from_snapshot(snapshot)
        with self._state.lock:
            self.check_open()
            if restored.agent_id not in self._state.registrations:
                raise ValueError("Completed run requires a registered agent")
            existing = self._state.runs.get(restored.id)
            if existing is None:
                self._state.runs[restored.id] = restored
                self._state.archived_run_ids.add(restored.id)
                completion: Future[RunState] = Future()
                completion.set_result(snapshot.model_copy(deep=True))
                self._state.completions[restored.id] = completion
                self._visible_run_ids.add(restored.id)
                return restored
        if not existing._completed.done() or existing.snapshot() != snapshot:
            raise RuntimeError("Run identity already has an execution owner")
        return existing

    def completion(self, run_id: str) -> Future[RunState]:
        """Observe terminal handling, including application persistence failures."""
        with self._state.lock:
            future = self._state.completions.get(run_id)
        if future is None:
            raise ValueError("Run is not owned by this coordinator")
        return future

    def _check_physical_owner(self, run_id: str) -> None:
        with self._state.lock:
            archived = run_id in self._state.archived_run_ids
        if archived:
            raise ValueError("Physical cleanup requires a locally owned execution")

    def add_completion_cleanup(
        self, run_id: str, callback: Callable[[], None]
    ) -> Future[None]:
        """Clean up local resources after completion or release, once workers drain."""
        run = self.run(run_id)
        self._check_physical_owner(run_id)
        completion: Future[None] = Future()
        completion.set_running_or_notify_cancel()
        with self._state.lock:
            self._state.cleanup.setdefault(run_id, []).append(completion)

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

        run._completed.add_done_callback(lambda _future: run.add_idle_callback(start))
        return completion

    def _cleanup_for(self, run_id: str) -> list[Future[None]]:
        with self._state.lock:
            return list(self._state.cleanup.get(run_id, ()))

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

    def begin(self, run: Run) -> None:
        if self._ownership is not None:
            self._ownership.register(run)

    def abort_start(self, run: Run) -> None:
        if self._ownership is not None:
            self._ownership.abort_start(run.id)

    def finish(self, run: Run) -> None:
        """Release ownership after execution and event workers drain."""
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
            self._state.registrations[info.id] = info.model_copy(deep=True)
            self._visible_agents[info.id] = info.model_copy(deep=True)

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

    def discovery(self, parent_id: str) -> list[AgentInfo]:
        # Never acquire a run lock under the coordinator lock. Starts use the reverse order.
        with self._state.lock:
            active_runs = {
                binding.run.agent_id: binding.run
                for binding in self._state.bindings.values()
            }
            registrations = [
                info.model_copy(deep=True)
                for info in self._state.registrations.values()
                if info.parent_id == parent_id
            ]
            latest = dict(self._state.latest)
            visible_runs = set(self._visible_run_ids)
        result: list[AgentInfo] = []
        for registered in registrations:
            info = self._lookup(registered.id, parent_id)
            if info is None:
                continue
            active = active_runs.get(info.id)
            saved = latest.get(info.id)
            if active is not None and active.id in visible_runs:
                result.append(
                    info.model_copy(
                        update={"latest_run_id": active.id, "status": active.status}
                    )
                )
            elif saved is not None and saved.run_id in visible_runs:
                result.append(
                    info.model_copy(
                        update={"latest_run_id": saved.run_id, "status": saved.status}
                    )
                )
            else:
                result.append(info)
        return result

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
                binding.run.agent_id == run.agent_id
                for binding in self._state.bindings.values()
            ):
                raise RuntimeError("Agent is already running or draining")
            if run.id in self._state.runs:
                raise RuntimeError("Run identity was already used")
            previous = self._state.latest.get(run.agent_id)
            if (
                previous is not None
                and previous.run_id == run.id
                and previous.status.is_terminal
            ):
                raise RuntimeError("Run is already complete")
            binding = RunCoordination(self, run)
            self._state.bindings[run.id] = binding
            self._state.runs[run.id] = run
            completion = self._state.completions.get(run.id)
            if completion is None:
                completion = Future()
                completion.set_running_or_notify_cancel()
                self._state.completions[run.id] = completion
            stop = self._state.completion_observers.pop(run.id, None)
            if stop is not None:
                stop.set()
            self._visible_run_ids.add(run.id)
        return binding

    def close(self, timeout: float = DEFAULT_AGENT_WAIT_SECONDS) -> bool:
        if not 0 <= timeout <= OPERATION_TIMEOUT_SECONDS:
            raise ValueError("Close timeout is outside its allowed bounds")
        with self._state.lock:
            self._state.closed = True
            for stop in self._state.completion_observers.values():
                stop.set()
            bindings = list(self._state.bindings.values())
        with self._state.lock:
            released_ids = set(self._state.completions) - set(self._state.runs)
        for binding in bindings:
            with binding._lock:
                binding._links.close()
                for run_id in released_ids:
                    binding.children.pop(run_id, None)
            binding.run.cancel()
        deadline = time.monotonic() + timeout
        for binding in bindings:
            try:
                binding.run._completed.result(
                    timeout=max(0, deadline - time.monotonic())
                )
            except TimeoutError:
                return False
            if not binding.run.wait_for_idle(
                timeout=max(0, deadline - time.monotonic())
            ):
                return False
        with self._state.lock:
            completions = [
                future
                for run_id, future in self._state.completions.items()
                if run_id not in released_ids
            ]
            cleanup = [
                future
                for run_id, futures in self._state.cleanup.items()
                if run_id not in released_ids
                for future in futures
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
            self._state.agent_views.clear()
            self._state.bindings.clear()
            self._state.latest.clear()
        return True

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
            self._state.registrations[agent.id] = info.model_copy(deep=True)
            self._visible_agents[agent.id] = info.model_copy(deep=True)
            self._state.agents[agent.id] = agent
            self._state.agent_views[agent.id] = self._view_id
            return info

    def unregister_child(self, agent_id: str) -> None:
        with self._state.lock:
            self._state.agents.pop(agent_id)
            self._state.agent_views.pop(agent_id, None)
            self._state.registrations.pop(agent_id)
            self._visible_agents.pop(agent_id, None)

    def loaded_child(self, agent_id: str, parent_id: str) -> Agent | None:
        if self._lookup(agent_id, parent_id) is None:
            raise ValueError("Agent is not available to this parent")
        with self._state.lock:
            agent = self._state.agents.get(agent_id)
            if self._state.agent_views.get(agent_id) != self._view_id:
                agent = None
            if agent is None and self._directory is None:
                raise ValueError("Agent restoration is unavailable")
            return agent

    def active_run(self, agent_id: str) -> Run | None:
        with self._state.lock:
            return next(
                (
                    binding.run
                    for binding in reversed(self._state.bindings.values())
                    if binding.run.agent_id == agent_id
                ),
                None,
            )

    def child_run(self, run_id: str, parent_id: str) -> Run | None:
        with self._state.lock:
            run = self._state.runs.get(run_id)
        if run is None:
            return None
        if self._lookup(run.agent_id, parent_id) is None:
            raise ValueError("Run is not available to this parent")
        with self._state.lock:
            visible = run_id in self._visible_run_ids
        if not visible:
            self._read_visible_run(run_id, parent_id, agent_id=run.agent_id)
        return run

    def release(self, run: Run) -> None:
        snapshot = run.snapshot()
        with self._state.lock:
            if snapshot.status == RunStatus.RUNNING:
                self._state.runs.pop(run.id, None)
                previous = self._state.latest.get(run.agent_id)
                if previous is None or previous.run_id != run.id:
                    self._state.completions.pop(run.id, None)
            if (
                self._state.registrations[run.agent_id].parent_id is not None
                and snapshot.status != RunStatus.RUNNING
            ):
                self._state.latest[run.agent_id] = snapshot
            self._state.bindings.pop(run.id, None)
            info = self._visible_agents.get(run.agent_id)
            if info is not None and snapshot.status != RunStatus.RUNNING:
                self._visible_agents[run.agent_id] = info.model_copy(
                    update={
                        "latest_run_id": run.id,
                        "status": snapshot.status,
                    }
                )

    def _lookup(self, agent_id: str, parent_id: str) -> AgentInfo | None:
        with self._state.lock:
            info = self._visible_agents.get(agent_id)
        if self._directory is not None and info is None:
            info = self._directory.lookup_agent(agent_id, parent_id)
            if info is not None:
                if info.id != agent_id:
                    raise ValueError("Archive returned a different agent")
                self.register(info)
        if info is not None and info.parent_id != parent_id:
            raise ValueError("Agent is not available to this parent")
        return info

    def resolve_child(self, agent_id: str, parent_id: str) -> Agent:
        if self._lookup(agent_id, parent_id) is None:
            raise ValueError("Agent is not available to this parent")
        with self._state.lock:
            if self._state.agent_views.get(agent_id) == self._view_id:
                if agent := self._state.agents.get(agent_id):
                    return agent
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
        with self._state.lock:
            self.check_open()
            if self._state.agent_views.get(agent_id) == self._view_id:
                if existing := self._state.agents.get(agent_id):
                    return existing
            if any(
                binding.run.agent_id == agent_id
                for binding in self._state.bindings.values()
            ):
                raise RuntimeError("Agent is already running or draining")
            if (
                agent_id not in self._state.agents
                and len(self._state.agents) >= MAX_LOADED_AGENTS
            ):
                raise ValueError("Loaded agent limit exceeded")
            self._state.agents[agent_id] = restored
            self._state.agent_views[agent_id] = self._view_id
        return restored

    def _read_visible_run(
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
        return self._read_visible_run(
            run_id, parent_id, agent_id=saved.agent_id if saved is not None else None
        )


class _ChildDependency(BaseModel):
    run_id: str
    observed: bool = False


class RunCoordination:
    """Track foreground dependencies and cancellation links for one parent execution."""

    def __init__(
        self,
        coordinator: AgentCoordinator,
        run: Run,
    ) -> None:
        self.coordinator = coordinator
        self.run = run
        self.children: dict[str, _ChildDependency] = {}
        self._links = ExitStack()
        self._finished = False
        self._lock = run._lock

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
    ) -> Run:
        run = agent.start(
            messages=messages,
            max_steps=max_steps,
            coordinator=self.coordinator,
            cancellation=CancellationSignal(),
            parent_run_id=self.run.id,
            parent_tool_call_id=call_id,
            parent_message_id=message_id,
            _event_parent=self.run._delivery
            if lifetime == AgentLifetime.FOREGROUND
            else None,
        )
        if lifetime == AgentLifetime.FOREGROUND:
            with self._lock:
                if self._finished:
                    run.cancel()
                    self.run._work.tracker.started()
                    run.add_idle_callback(self.run._work.tracker.finished)
                else:
                    self._include_predecessors(run)
                    self._attach(run)
        return run

    def _include_predecessors(self, run: Run) -> None:
        """Retain completed background history consumed by this foreground child."""
        previous_id = run.snapshot().previous_run_id
        predecessors: list[Run] = []
        seen: set[str] = set()
        while (
            previous_id and previous_id not in self.children and previous_id not in seen
        ):
            seen.add(previous_id)
            previous = self.coordinator.child_run(previous_id, self.run.agent_id)
            if previous is None:
                break
            snapshot = previous.snapshot()
            if snapshot.parent_run_id != self.run.id or not snapshot.status.is_terminal:
                break
            predecessors.append(previous)
            previous_id = snapshot.previous_run_id
        for previous in reversed(predecessors):
            child = _ChildDependency(run_id=previous.id)
            child.observed = True
            self.children[previous.id] = child

    def _attach(self, run: Run) -> None:
        run_id = run.id
        self.children[run_id] = _ChildDependency(run_id=run_id)
        self._links.enter_context(
            self.run._cancellation_signal.on_cancel(
                lambda: self.coordinator.cancel_child(run_id, self.run.agent_id)
            )
        )

    def attach_children(self, run_ids: Sequence[str]) -> None:
        """Reconnect foreground dependencies from live or archived terminal runs."""
        children = self.child_runs(run_ids)
        with self._lock:
            for run in children:
                if run.id not in self.children:
                    self._attach(run)

    def observe_children(self, run_ids: Sequence[str]) -> None:
        """Mark failures consumed by a successful delegation completion callback."""
        with self._lock:
            for run_id in run_ids:
                child = self.children.get(run_id)
                if child is not None:
                    child.observed = True

    def observed_children(self) -> list[str]:
        with self._lock:
            return [run_id for run_id, child in self.children.items() if child.observed]

    def child_runs(self, run_ids: Sequence[str]) -> list[Run]:
        """Resolve tool dependencies within this parent's authorized child view."""
        runs = []
        for run_id in run_ids:
            run = self.coordinator.child_run(run_id, self.run.agent_id)
            if run is None:
                snapshot = self.coordinator.saved_run(run_id, self.run.agent_id)
                run = self.coordinator.restore_completed(snapshot)
            runs.append(run)
        return runs

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
            children = list(self.children.values())
        if cancel:
            for child in children:
                self.coordinator.cancel_child(child.run_id, self.run.agent_id)
        for child in children:
            local = self.coordinator.child_run(child.run_id, self.run.agent_id)
            if local is not None:
                self.run._work.tracker.started()
                local.add_idle_callback(self.run._work.tracker.finished)
            for cleanup in self.coordinator._cleanup_for(child.run_id):
                self.run._work.track_operation(cleanup)
        deadline = time.monotonic() + (
            CHILD_TERMINAL_TIMEOUT_SECONDS if cancel else OPERATION_TIMEOUT_SECONDS
        )
        failure: RunFailed | None = None
        records: list[RunState] = []
        try:
            for child in children:
                try:
                    future = self.coordinator.completion(child.run_id)
                    if not cancel:
                        wait_operation(
                            future,
                            self.run._cancellation_signal,
                            max(0, deadline - time.monotonic()),
                        )
                    state = future.result(timeout=max(0, deadline - time.monotonic()))
                    records.append(state)
                    result_from_snapshot(state)
                except RunFailed as error:
                    if not child.observed and not cancel and failure is None:
                        failure = error
                except AgentCancelled:
                    if not cancel:
                        self.run._cancellation_signal.check()
                    logger.debug("Child execution was cancelled: %s", child.run_id)
                except TimeoutError as error:
                    self.coordinator.cancel_child(child.run_id, self.run.agent_id)
                    if not cancel:
                        raise
                    raise TimeoutError(
                        "Child execution did not publish a terminal record after cancellation"
                    ) from error
        finally:
            self._links.close()
        if failure is not None:
            raise failure
        return records

    def child_states(self, run_ids: Sequence[str]) -> list[RunState]:
        return [
            self.coordinator.run_state(run_id, self.run.agent_id) for run_id in run_ids
        ]

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

    def _check(self) -> None:
        self.owner.run._cancellation_signal.check()
        if (
            not self.active.is_set()
            or self.owner._finished
            or not self.owner.run._accepting
        ):
            raise RuntimeError("Coordination requires an active tool invocation")
        self.owner.coordinator.check_open()

    def discovery(self) -> list[AgentInfo]:
        self._check()
        return self.owner.coordinator.discovery(self.owner.run.agent_id)

    def spawn_agent(
        self,
        agent: Agent,
        *,
        name: str,
        description: str,
        max_steps: int,
        messages: Sequence[Message],
        restoration_config: BaseModel | None = None,
        lifetime: AgentLifetime = AgentLifetime.FOREGROUND,
    ) -> SpawnResult:
        self._check()
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
        self._check()
        coordinator = self.owner.coordinator
        agent = coordinator.loaded_child(agent_id, self.owner.run.agent_id)
        if agent is None:
            agent = self.owner.run._work.blocking(
                lambda: coordinator.resolve_child(agent_id, self.owner.run.agent_id),
                self.owner.run._cancellation_signal,
            )
        self._check()
        previous = coordinator.active_run(agent_id)
        if previous is not None and previous.status.is_terminal:
            idle = self.owner.run._work.blocking(
                lambda: previous.wait_for_idle(timeout=OPERATION_TIMEOUT_SECONDS),
                self.owner.run._cancellation_signal,
            )
            if not idle:
                raise TimeoutError("Previous agent execution is still draining")
        self._check()
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
        self._check()
        if not 0 <= timeout <= OPERATION_TIMEOUT_SECONDS:
            raise ValueError("Wait timeout is outside its allowed bounds")
        with self.owner._lock:
            child = self.owner.children.get(run_id)
        run = self.owner.coordinator.child_run(run_id, self.owner.run.agent_id)
        if run is not None:
            try:
                result = wait_operation(
                    run._completed, self.owner.run._cancellation_signal, timeout
                )
                result = run.result(timeout=0)
            except TimeoutError:
                return None
            except (RunFailed, AgentCancelled):
                if child is not None:
                    with self.owner._lock:
                        child.observed = True
                raise
            if child is not None:
                with self.owner._lock:
                    child.observed = True
            return result
        coordinator = self.owner.coordinator
        latest = coordinator.saved_run(
            run_id, self.owner.run.agent_id, load_archive=False
        )
        if latest is not None and latest.status.is_terminal:
            return result_from_snapshot(latest)

        if timeout == 0:
            return None

        def wait_remote() -> RunResult | None:
            deadline = time.monotonic() + timeout
            while True:
                self.owner.run._cancellation_signal.check()
                if coordinator._remote_status(
                    run_id, self.owner.run.agent_id
                ).is_terminal:
                    return result_from_snapshot(
                        coordinator._read_visible_run(run_id, self.owner.run.agent_id)
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                try:
                    wait_operation(
                        Future(),
                        self.owner.run._cancellation_signal,
                        min(REMOTE_POLL_SECONDS, remaining),
                    )
                except TimeoutError:
                    continue

        try:
            return self.owner.run._work.blocking(
                wait_remote, self.owner.run._cancellation_signal, timeout=timeout
            )
        except TimeoutError:
            return None

    def cancel_run(self, run_id: str) -> None:
        self._check()
        run = self.owner.coordinator.child_run(run_id, self.owner.run.agent_id)
        if run is not None:
            run.cancel()
            return
        coordinator = self.owner.coordinator

        def cancel_remote() -> None:
            record = coordinator._read_visible_run(run_id, self.owner.run.agent_id)
            if record.status.is_terminal:
                return
            if coordinator._directory is None:
                raise ValueError("Remote run cancellation is unavailable")
            coordinator._directory.cancel_run(run_id, self.owner.run.agent_id)

        self.owner.run._work.blocking(
            cancel_remote, self.owner.run._cancellation_signal
        )

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
        with self.owner._lock:
            if self.owner._finished and run_id in self.owner.children:
                self.owner.run._work.track_operation(future)
        return future
