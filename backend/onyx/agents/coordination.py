"""Optional, caller-owned agent discovery and execution coordination."""

import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import Future
from contextlib import ExitStack
from typing import Literal, overload
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

from onyx.agents.concurrency import (
    CLEANUP_SECONDS,
    OPERATION_TIMEOUT_SECONDS,
    ExecutionWork,
    wait_operation,
)
from onyx.agents.events import AgentEvent
from onyx.agents.models import AgentContext, RunResult, RunSnapshot
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
from onyx.agents.transcript import (
    AgentRestorationConfig,
    RunStatus,
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


class AgentInfo(BaseModel):
    """Visible identity and latest run status, without conversation content."""

    model_config = ConfigDict(frozen=True)
    id: str
    path: str
    parent_id: str | None
    description: str
    restoration_config: AgentRestorationConfig | None
    latest_run_id: str | None = None
    status: RunStatus | None = None


class _CoordinatorState:
    def __init__(self) -> None:
        self.registrations: dict[str, AgentInfo] = {}
        self.agents: dict[str, Agent] = {}
        self.agent_views: dict[str, UUID] = {}
        self.bindings: dict[str, RunCoordination] = {}
        self.runs: dict[str, Run] = {}
        self.archived_run_ids: set[str] = set()
        self.completions: dict[str, Future[RunSnapshot]] = {}
        self.cleanup: dict[str, list[Future[None]]] = {}
        self.latest: dict[str, RunSnapshot] = {}
        self.work = ExecutionWork()
        self.remote_observers: dict[str, threading.Event] = {}
        self.closed = False
        self.lock = threading.RLock()


class AgentCoordinator:
    """Own agent identities, loaded conversations, and their active or saved runs."""

    def __init__(
        self,
        *,
        agents: Sequence[AgentInfo] = (),
        lookup_agent: Callable[[str, str], AgentInfo | None] | None = None,
        resolve_agent: Callable[[str, str], Agent] | None = None,
        read_run: Callable[[str, str], RunSnapshot | None] | None = None,
        read_run_status: Callable[[str, str], RunStatus] | None = None,
        on_event: Callable[[AgentEvent], None] | None = None,
        on_complete: Callable[[RunSnapshot], None] | None = None,
        on_start: Callable[[Agent, Run, AgentInfo], Callable[[], None] | None]
        | None = None,
        cancel_run: Callable[[str, str], None] | None = None,
    ) -> None:
        self._state = _CoordinatorState()
        self._view_id = uuid4()
        self._visible_agents: dict[str, AgentInfo] = {}
        self._visible_run_ids: set[str] = set()
        self._lookup_agent = lookup_agent
        self._resolve_agent = resolve_agent
        self._read_run = read_run
        self._read_run_status = read_run_status
        self._on_event = on_event
        self._on_complete = on_complete
        self._on_start = on_start
        self._cancel_run = cancel_run
        self._share_state(self._state)
        for info in agents:
            if info.id in self._registrations:
                raise ValueError("Duplicate agent identity")
            self.register(info)

    def _share_state(self, state: _CoordinatorState) -> None:
        self._state = state
        self._registrations = state.registrations
        self._agents = state.agents
        self._bindings = state.bindings
        self._latest = state.latest
        self._lock = state.lock

    def view(
        self,
        *,
        lookup_agent: Callable[[str, str], AgentInfo | None] | None = None,
        resolve_agent: Callable[[str, str], Agent] | None = None,
        read_run: Callable[[str, str], RunSnapshot | None] | None = None,
        read_run_status: Callable[[str, str], RunStatus] | None = None,
        visible_run_ids: Sequence[str] = (),
        on_complete: Callable[[RunSnapshot], None] | None = None,
        on_start: Callable[[Agent, Run, AgentInfo], Callable[[], None] | None]
        | None = None,
        cancel_run: Callable[[str, str], None] | None = None,
    ) -> "AgentCoordinator":
        """Bind fresh parent resources while retaining the same execution owner."""
        self.check_open()
        view = AgentCoordinator(
            lookup_agent=lookup_agent,
            resolve_agent=resolve_agent,
            read_run=read_run,
            read_run_status=read_run_status or self._read_run_status,
            on_event=self._on_event,
            on_complete=on_complete if on_complete is not None else self._on_complete,
            on_start=on_start if on_start is not None else self._on_start,
            cancel_run=cancel_run if cancel_run is not None else self._cancel_run,
        )
        view._share_state(self._state)
        with self._lock:
            if lookup_agent is None and read_run is None:
                view._visible_agents.update(self._visible_agents)
                view._visible_run_ids.update(self._visible_run_ids)
                view._lookup_agent = self._lookup_agent
                view._read_run = self._read_run
                if resolve_agent is None:
                    view._view_id = self._view_id
                    view._resolve_agent = self._resolve_agent
            view._visible_run_ids.update(visible_run_ids)
        return view

    def run(self, run_id: str) -> Run:
        """Return a retained run handle; its execution can be local or remote."""
        with self._lock:
            run = self._state.runs.get(run_id)
        if run is None:
            raise ValueError("Run is not owned by this coordinator")
        return run

    def claim_resume(
        self, snapshot: RunSnapshot, context: AgentContext
    ) -> tuple[Run | None, Callable[[], None] | None]:
        """Claim a retained handle and return rollback for failed reconstruction."""
        with self._lock:
            self.check_open()
            run = self._state.runs.get(snapshot.run_id)
        if run is None:
            return None, None
        restore = run.claim_resume(snapshot, context)
        with self._lock:
            stop = self._state.remote_observers.pop(run.id, None)
        if stop is not None:
            stop.set()

        def rollback() -> None:
            restore()
            self.release_execution(run)
            if run.is_remote:
                self.transfer(run)

        return run, rollback

    def bind_agent(self, agent: Agent) -> None:
        """Keep the current child implementation after a physical owner change."""
        with self._lock:
            info = self._registrations[agent.id]
            if info.parent_id is not None:
                self._agents[agent.id] = agent
                self._state.agent_views[agent.id] = self._view_id

    def release_execution(self, run: Run) -> None:
        """Drop physical event bindings after an explicit suspended handoff."""
        with self._lock:
            binding = self._bindings.get(run.id)
        if binding is not None:
            with binding._lock:
                if (
                    binding.run._state.handoff is not None
                    and not binding.run._state.segment_active
                ):
                    binding.detach()
                    with self._lock:
                        self._agents.pop(run.agent_id, None)
                        self._state.agent_views.pop(run.agent_id, None)

    def transfer(self, run: Run) -> None:
        """Retain a logical handle while another process owns its execution."""
        with run._state.lock:
            if (
                run._state.handoff is None
                or run._state.segment_active
                or not run.is_remote
            ):
                raise ValueError("Only a remotely released execution can be observed")
        with self._lock:
            if self._state.closed:
                return
            if run.id in self._state.remote_observers:
                raise ValueError("Remote execution already has an observer")
            stop = threading.Event()
            self._state.remote_observers[run.id] = stop
            info = self._registrations[run.agent_id]
        parent_id = info.parent_id or ""

        def observe() -> None:
            while not stop.is_set():
                try:
                    status = self._remote_status(run.id, parent_id)
                    if status.is_terminal:
                        snapshot = (
                            self._read_run(run.id, parent_id)
                            if self._read_run
                            else None
                        )
                        if (
                            snapshot is None
                            or snapshot.run_id != run.id
                            or snapshot.agent_id != run.agent_id
                        ):
                            raise ValueError(
                                "Transferred execution returned a different identity"
                            )
                        with run._state.lock:
                            if stop.is_set() or not run.is_remote:
                                return
                            run._state.record = snapshot.model_copy(deep=True)
                            run._state.accepting = False
                        run._state.completed.set_result(None)
                        run._finalize()
                        return
                    with run._state.lock:
                        if not stop.is_set() and run._state.remote_cancel is not None:
                            run._state.record.status = status
                except Exception:
                    # An unavailable reader does not establish the remote execution's outcome.
                    logger.exception("Could not read transferred execution; retrying")
                stop.wait(REMOTE_POLL_SECONDS)

        try:
            self._state.work.start(observe)
        except BaseException:
            stop.set()
            with self._lock:
                if self._state.remote_observers.get(run.id) is stop:
                    self._state.remote_observers.pop(run.id)
            raise

    def _remote_status(self, run_id: str, parent_id: str) -> RunStatus:
        if self._read_run_status is not None:
            return self._read_run_status(run_id, parent_id)
        return self._read_visible_run(run_id, parent_id).status

    def restore_completed(self, snapshot: RunSnapshot) -> Run:
        """Retain an archived terminal result without executing or saving it again."""
        restored = Run.from_snapshot(snapshot)
        with self._lock:
            self.check_open()
            info = self._registrations.get(restored.agent_id)
            if info is None:
                raise ValueError("Completed run requires a registered agent")
            existing = self._state.runs.get(restored.id)
            if existing is None:
                self._state.runs[restored.id] = restored
                self._state.archived_run_ids.add(restored.id)
                completion: Future[RunSnapshot] = Future()
                completion.set_result(snapshot.model_copy(deep=True))
                self._state.completions[restored.id] = completion
                self._visible_run_ids.add(restored.id)
                if info.latest_run_id in (None, restored.id):
                    self._latest.setdefault(
                        restored.agent_id, snapshot.model_copy(deep=True)
                    )
                return restored
        if not existing._state.completed.done() or existing.snapshot() != snapshot:
            raise RuntimeError("Run identity already has an execution owner")
        return existing

    def completion(self, run_id: str) -> Future[RunSnapshot]:
        """Observe terminal handling, including application persistence failures."""
        with self._lock:
            future = self._state.completions.get(run_id)
        if future is None:
            raise ValueError("Run is not owned by this coordinator")
        return future

    def _check_physical_owner(self, run_id: str) -> None:
        with self._lock:
            archived = run_id in self._state.archived_run_ids
            run = self._state.runs[run_id]
        if archived or run.is_remote:
            raise ValueError("Physical cleanup requires a locally owned execution")

    def add_completion_cleanup(
        self, run_id: str, callback: Callable[[], None]
    ) -> Future[None]:
        """Run resource cleanup after terminal output and the final segment drains."""
        run = self.run(run_id)
        self._check_physical_owner(run_id)
        completion: Future[None] = Future()
        completion.set_running_or_notify_cancel()
        with self._lock:
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

        run.add_done_callback(lambda _snapshot: run.add_idle_callback(start))
        return completion

    def _cleanup_for(self, run_id: str) -> list[Future[None]]:
        with self._lock:
            return list(self._state.cleanup.get(run_id, ()))

    def _complete(self, snapshot: RunSnapshot) -> None:
        run = self.run(snapshot.run_id)
        with run._state.lock:
            ownerless = run._state.restart is None and not run._state.segment_active
        if ownerless:
            run.add_idle_callback(lambda: self.release(run))
        future = self.completion(snapshot.run_id)
        callback = None if run.is_remote else self._on_complete
        if callback is None:
            future.set_result(snapshot.model_copy(deep=True))
            return

        def complete() -> None:
            try:
                callback(snapshot.model_copy(deep=True))
            except BaseException as error:
                logger.exception("Agent completion handling failed")
                future.set_exception(error)
            else:
                future.set_result(snapshot.model_copy(deep=True))

        complete()

    def register(self, info: AgentInfo) -> None:
        with self._lock:
            self.check_open()
            existing = self._registrations.get(info.id)
            if existing is not None and existing.parent_id != info.parent_id:
                raise ValueError("Agent registration changes its parent")
            self._registrations[info.id] = info.model_copy(deep=True)
            self._visible_agents[info.id] = info.model_copy(deep=True)

    def registration(self, agent_id: str) -> AgentInfo | None:
        with self._lock:
            info = self._registrations.get(agent_id)
            return info.model_copy(deep=True) if info is not None else None

    def registrations(self) -> list[AgentInfo]:
        with self._lock:
            return [info.model_copy(deep=True) for info in self._registrations.values()]

    def discovery(self, parent_id: str) -> list[AgentInfo]:
        # Never acquire a run lock under the coordinator lock. Starts use the reverse order.
        with self._lock:
            active_runs = {
                binding.run.agent_id: binding.run for binding in self._bindings.values()
            }
            registrations = [
                info.model_copy(deep=True)
                for info in self._registrations.values()
                if info.parent_id == parent_id
            ]
            latest = dict(self._latest)
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

    def bind(
        self,
        run: Run,
        work: ExecutionWork,
        publish: Callable[[AgentEvent], None],
        cancellation: CancellationSignal,
    ) -> "RunCoordination":
        with self._lock:
            if self._state.closed:
                raise RuntimeError("Agent coordination is closed")
            if run.agent_id not in self._registrations:
                self.register(
                    AgentInfo(
                        id=run.agent_id,
                        path="/root",
                        parent_id=None,
                        description="",
                        restoration_config=None,
                    )
                )
            existing = self._bindings.get(run.id)
            if existing is not None:
                if existing.run is not run:
                    raise RuntimeError("Run already has an execution owner")
                binding = existing
            else:
                if any(
                    binding.run.agent_id == run.agent_id
                    for binding in self._bindings.values()
                ):
                    raise RuntimeError("Agent is already running or draining")
                if run.id in self._state.runs:
                    raise RuntimeError("Run identity was already used")
                binding = RunCoordination(self, run, work, publish, cancellation)
                self._bindings[run.id] = binding
                self._state.runs[run.id] = run
                completion: Future[RunSnapshot] = Future()
                completion.set_running_or_notify_cancel()
                self._state.completions[run.id] = completion
            self._visible_run_ids.add(run.id)
        if existing is not None:
            existing.rebind(work, publish, cancellation, coordinator=self)
            return existing
        if self._on_event is not None:
            listener = self._on_event
            run.subscribe(
                lambda event: listener(event) if event.run_id == run.id else None
            )
        run._add_terminal_callback(
            lambda completed: binding.coordinator._complete(completed.snapshot())
        )
        return binding

    def notify_start(self, agent: Agent, run: Run) -> Callable[[], None] | None:
        """Register application ownership before execution starts."""
        if self._on_start is not None:
            with self._lock:
                info = self._registrations[agent.id].model_copy(deep=True)
            return self._on_start(agent, run, info)
        return None

    def close(self, timeout: float = DEFAULT_AGENT_WAIT_SECONDS) -> bool:
        if not 0 <= timeout <= OPERATION_TIMEOUT_SECONDS:
            raise ValueError("Close timeout is outside its allowed bounds")
        with self._lock:
            self._state.closed = True
            runs = list(self._state.runs.values())
            for stop in self._state.remote_observers.values():
                stop.set()
            bindings = list(self._bindings.values())
        remote_ids = {run.id for run in runs if run.is_remote}
        local_bindings: list[RunCoordination] = []
        for binding in bindings:
            with binding._lock:
                binding._links.close()
                for run_id in remote_ids:
                    binding.children.pop(run_id, None)
            if binding.run._cancel_if_local():
                local_bindings.append(binding)
            else:
                remote_ids.add(binding.run.id)
        deadline = time.monotonic() + timeout
        for binding in local_bindings:
            try:
                binding.run._state.completed.result(
                    timeout=max(0, deadline - time.monotonic())
                )
            except TimeoutError:
                return False
            if not binding.run.wait_for_idle(
                timeout=max(0, deadline - time.monotonic())
            ):
                return False
        with self._lock:
            completions = [
                future
                for run_id, future in self._state.completions.items()
                if run_id not in remote_ids
            ]
            cleanup = [
                future
                for run_id, futures in self._state.cleanup.items()
                if run_id not in remote_ids
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
        with self._lock:
            self._agents.clear()
            self._state.agent_views.clear()
            self._bindings.clear()
            self._latest.clear()
        return True

    def check_open(self) -> None:
        with self._lock:
            if self._state.closed:
                raise RuntimeError("Agent coordination is closed")

    def register_child(
        self,
        agent: Agent,
        *,
        parent_id: str,
        name: str,
        description: str,
        restoration_config: AgentRestorationConfig | None,
    ) -> AgentInfo:
        if not name or "/" in name:
            raise ValueError("Agent name must be a nonempty label without slashes")
        with self._lock:
            self.check_open()
            parent = self._registrations[parent_id]
            ancestor = parent
            depth = 0
            while ancestor.parent_id is not None:
                depth += 1
                ancestor = self._registrations[ancestor.parent_id]
            if depth >= MAX_CHILD_DEPTH:
                raise ValueError("Agent nesting limit exceeded")
            if (
                agent.id in self._registrations
                or len(self._agents) >= MAX_LOADED_AGENTS
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
            self._registrations[agent.id] = info.model_copy(deep=True)
            self._visible_agents[agent.id] = info.model_copy(deep=True)
            self._agents[agent.id] = agent
            self._state.agent_views[agent.id] = self._view_id
            return info

    def unregister_child(self, agent_id: str) -> None:
        with self._lock:
            self._agents.pop(agent_id)
            self._state.agent_views.pop(agent_id, None)
            self._registrations.pop(agent_id)
            self._visible_agents.pop(agent_id, None)

    def loaded_child(self, agent_id: str, parent_id: str) -> Agent | None:
        if self._lookup(agent_id, parent_id) is None:
            raise ValueError("Agent is not available to this parent")
        with self._lock:
            agent = self._agents.get(agent_id)
            if self._state.agent_views.get(agent_id) != self._view_id:
                agent = None
            if agent is None and self._resolve_agent is None:
                raise ValueError("Agent restoration is unavailable")
            return agent

    def active_run(self, agent_id: str) -> Run | None:
        with self._lock:
            return next(
                (
                    binding.run
                    for binding in reversed(self._bindings.values())
                    if binding.run.agent_id == agent_id
                ),
                None,
            )

    def child_run(self, run_id: str, parent_id: str) -> Run | None:
        with self._lock:
            run = self._state.runs.get(run_id)
        if run is None:
            return None
        if self._lookup(run.agent_id, parent_id) is None:
            raise ValueError("Run is not available to this parent")
        with self._lock:
            visible = run_id in self._visible_run_ids
        if not visible:
            self._read_visible_run(run_id, parent_id, agent_id=run.agent_id)
        return run

    def release(self, run: Run) -> None:
        snapshot = run.snapshot()
        with self._lock:
            if snapshot.status == RunStatus.RUNNING:
                self._state.runs.pop(run.id, None)
                self._state.completions.pop(run.id, None)
            if (
                self._registrations[run.agent_id].parent_id is not None
                and snapshot.status != RunStatus.RUNNING
            ):
                self._latest[run.agent_id] = snapshot
            self._bindings.pop(run.id, None)
            info = self._visible_agents.get(run.agent_id)
            if info is not None and snapshot.status != RunStatus.RUNNING:
                self._visible_agents[run.agent_id] = info.model_copy(
                    update={
                        "latest_run_id": run.id,
                        "status": snapshot.status,
                    }
                )

    def _lookup(self, agent_id: str, parent_id: str) -> AgentInfo | None:
        with self._lock:
            info = self._visible_agents.get(agent_id)
        if self._lookup_agent is not None and info is None:
            info = self._lookup_agent(agent_id, parent_id)
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
        with self._lock:
            if self._state.agent_views.get(agent_id) == self._view_id:
                if agent := self._agents.get(agent_id):
                    return agent
            if agent_id not in self._agents and len(self._agents) >= MAX_LOADED_AGENTS:
                raise ValueError("Loaded agent limit exceeded")
        if self._resolve_agent is None:
            raise ValueError("Agent restoration is unavailable")
        restored = self._resolve_agent(agent_id, parent_id)
        if restored.id != agent_id:
            raise ValueError("Restoration returned a different agent")
        with self._lock:
            self.check_open()
            if self._state.agent_views.get(agent_id) == self._view_id:
                if existing := self._agents.get(agent_id):
                    return existing
            if any(
                binding.run.agent_id == agent_id for binding in self._bindings.values()
            ):
                raise RuntimeError("Agent is already running or draining")
            if agent_id not in self._agents and len(self._agents) >= MAX_LOADED_AGENTS:
                raise ValueError("Loaded agent limit exceeded")
            self._agents[agent_id] = restored
            self._state.agent_views[agent_id] = self._view_id
        return restored

    def _read_visible_run(
        self, run_id: str, parent_id: str, *, agent_id: str | None = None
    ) -> RunSnapshot:
        """Authorize a specific run through this view's selected history."""
        record = (
            self._read_run(run_id, parent_id) if self._read_run is not None else None
        )
        if record is None:
            raise ValueError("Run is not available to this parent")
        if record.run_id != run_id or record.agent_id is None:
            raise ValueError("Archive returned a different run")
        if agent_id is not None and record.agent_id != agent_id:
            raise ValueError("Archive returned a different agent")
        if self._lookup(record.agent_id, parent_id) is None:
            raise ValueError("Run is not available to this parent")
        with self._lock:
            self._visible_run_ids.add(run_id)
        return record

    @overload
    def saved_run(
        self, run_id: str, parent_id: str, *, load_archive: Literal[True] = True
    ) -> RunSnapshot: ...

    @overload
    def saved_run(
        self, run_id: str, parent_id: str, *, load_archive: Literal[False]
    ) -> RunSnapshot | None: ...

    def saved_run(
        self, run_id: str, parent_id: str, *, load_archive: bool = True
    ) -> RunSnapshot | None:
        with self._lock:
            saved = next(
                (item for item in self._latest.values() if item.run_id == run_id), None
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


class _ChildExecution:
    def __init__(self, run: Run) -> None:
        self.run = run
        self.observed = False


class RunCoordination:
    """Track foreground dependencies and cancellation links for one parent execution."""

    def __init__(
        self,
        coordinator: AgentCoordinator,
        run: Run,
        work: ExecutionWork,
        publish: Callable[[AgentEvent], None],
        cancellation: CancellationSignal,
    ) -> None:
        self.coordinator = coordinator
        self.run = run
        self.work = work
        self.publish = publish
        self.cancellation = cancellation
        self.children: dict[str, _ChildExecution] = {}
        self._links = ExitStack()
        self._finished = False
        self._lock = run._state.lock

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
            inherited_event_sink=self.forward_event
            if lifetime == AgentLifetime.FOREGROUND
            else None,
            event_dispatcher=self.run._state.delivery.dispatcher
            if lifetime == AgentLifetime.FOREGROUND and self.run._state.delivery
            else None,
        )
        if lifetime == AgentLifetime.FOREGROUND:
            with self._lock:
                if self._finished:
                    run.cancel()
                    self.work.tracker.started()
                    run.add_idle_callback(self.work.tracker.finished)
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
            child = _ChildExecution(previous)
            child.observed = True
            self.children[previous.id] = child

    def _attach(self, run: Run) -> None:
        self.children[run.id] = _ChildExecution(run)
        self._links.enter_context(self.cancellation.on_cancel(run.cancel))

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

    def pending_children(self) -> list[Run]:
        with self._lock:
            return [
                child.run
                for child in self.children.values()
                if not child.run._state.completed.done()
            ]

    def validate_handoff(self) -> None:
        if self.pending_children():
            raise RunNotTransferable(
                "Foreground child runs must finish before parent transfer"
            )

    def forward_event(self, event: AgentEvent) -> None:
        with self._lock:
            publish = self.publish
        publish(event)

    def _publish_detached(self, event: AgentEvent) -> None:
        with self._lock:
            if self.run._state.accepting and self.run._state.delivery is not None:
                self.run._state.delivery.publish(event)

    def detach(self) -> None:
        with self._lock:
            if (
                self.run._state.handoff is not None
                and not self.run._state.segment_active
            ):
                self.publish = self._publish_detached

    def rebind(
        self,
        work: ExecutionWork,
        publish: Callable[[AgentEvent], None],
        cancellation: CancellationSignal,
        *,
        coordinator: AgentCoordinator | None = None,
    ) -> None:
        """Refresh a resumed parent's physical work without replacing its dependencies."""
        with self._lock:
            if coordinator is not None:
                self.coordinator = coordinator
            self.work = work
            self.publish = publish
            self.cancellation = cancellation
            self._finished = False
            self._links.close()
            for child in self.children.values():
                self._links.enter_context(cancellation.on_cancel(child.run.cancel))

    def finish(self, cancel: bool) -> list[RunSnapshot]:
        with self._lock:
            self._finished = True
            children = list(self.children.values())
        if cancel:
            if self.run._state.shutdown_requested:
                children = [child for child in children if child.run._cancel_if_local()]
            else:
                for child in children:
                    child.run.cancel()
        for child in children:
            self.work.tracker.started()
            child.run.add_idle_callback(self.work.tracker.finished)
            for cleanup in self.coordinator._cleanup_for(child.run.id):
                self.work.track_operation(cleanup)
        deadline = time.monotonic() + (
            CHILD_TERMINAL_TIMEOUT_SECONDS if cancel else OPERATION_TIMEOUT_SECONDS
        )
        failure: RunFailed | None = None
        try:
            for child in children:
                try:
                    if not cancel:
                        wait_operation(
                            child.run._state.completed,
                            self.cancellation,
                            max(0, deadline - time.monotonic()),
                        )
                    child.run.result(timeout=max(0, deadline - time.monotonic()))
                except RunFailed as error:
                    if not child.observed and not cancel and failure is None:
                        failure = error
                except AgentCancelled:
                    if not cancel:
                        self.cancellation.check()
                    logger.debug("Child execution was cancelled: %s", child.run.id)
                except TimeoutError as error:
                    child.run.cancel()
                    if not cancel:
                        raise
                    raise TimeoutError(
                        "Child execution did not publish a terminal record after cancellation"
                    ) from error
        finally:
            self._links.close()
        records = [child.run.snapshot() for child in children]
        if failure is not None:
            raise failure
        return records

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
        self.owner.cancellation.check()
        if (
            not self.active.is_set()
            or self.owner._finished
            or not self.owner.run._state.accepting
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
        restoration_config: AgentRestorationConfig | None = None,
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
            agent = self.owner.work.blocking(
                lambda: coordinator.resolve_child(agent_id, self.owner.run.agent_id),
                self.owner.cancellation,
            )
        self._check()
        previous = coordinator.active_run(agent_id)
        if previous is not None and previous.status.is_terminal:
            idle = self.owner.work.blocking(
                lambda: previous.wait_for_idle(timeout=OPERATION_TIMEOUT_SECONDS),
                self.owner.cancellation,
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
        run = (
            child.run
            if child
            else self.owner.coordinator.child_run(run_id, self.owner.run.agent_id)
        )
        if run is not None:
            try:
                result = wait_operation(
                    run._state.completed, self.owner.cancellation, timeout
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
                self.owner.cancellation.check()
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
                        self.owner.cancellation,
                        min(REMOTE_POLL_SECONDS, remaining),
                    )
                except TimeoutError:
                    continue

        try:
            return self.owner.work.blocking(
                wait_remote, self.owner.cancellation, timeout=timeout
            )
        except TimeoutError:
            return None

    def cancel_run(self, run_id: str) -> None:
        self._check()
        with self.owner._lock:
            child = self.owner.children.get(run_id)
        run = (
            child.run
            if child
            else self.owner.coordinator.child_run(run_id, self.owner.run.agent_id)
        )
        if run is not None:
            run.cancel()
            return
        coordinator = self.owner.coordinator

        def cancel_remote() -> None:
            record = coordinator._read_visible_run(run_id, self.owner.run.agent_id)
            if record.status.is_terminal:
                return
            if coordinator._cancel_run is None:
                raise ValueError("Remote run cancellation is unavailable")
            coordinator._cancel_run(run_id, self.owner.run.agent_id)

        self.owner.work.blocking(cancel_remote, self.owner.cancellation)

    def wait_for_idle(
        self, run_id: str, *, timeout: float = OPERATION_TIMEOUT_SECONDS
    ) -> bool:
        """Wait for owned child cleanup even after the invocation is cancelled."""
        with self.owner._lock:
            child = self.owner.children.get(run_id)
        run = (
            child.run
            if child
            else self.owner.coordinator.child_run(run_id, self.owner.run.agent_id)
        )
        if run is not None:
            self.owner.coordinator._check_physical_owner(run_id)
            return run.wait_for_idle(timeout)
        self.owner.coordinator.saved_run(run_id, self.owner.run.agent_id)
        raise ValueError("Physical cleanup cannot be observed for a remote run")

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
                self.owner.work.track_operation(future)
        return future

    def add_idle_callback(self, run_id: str, callback: Callable[[], None]) -> None:
        """Retain cleanup until an owned child is idle, including after cancellation."""
        with self.owner._lock:
            child = self.owner.children.get(run_id)
        run = (
            child.run
            if child
            else self.owner.coordinator.child_run(run_id, self.owner.run.agent_id)
        )
        if run is not None:
            self.owner.coordinator._check_physical_owner(run_id)
            run.add_idle_callback(callback)
            return
        self.owner.coordinator.saved_run(run_id, self.owner.run.agent_id)
        raise ValueError("Physical cleanup cannot be observed for a remote run")
