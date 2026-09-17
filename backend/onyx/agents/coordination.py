"""Optional, caller-owned agent discovery and execution coordination."""

import threading
import time
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from typing import Literal, overload

from pydantic import BaseModel, ConfigDict

from onyx.agents.concurrency import (
    CLEANUP_SECONDS,
    OPERATION_TIMEOUT_SECONDS,
    ExecutionWork,
    wait_operation,
)
from onyx.agents.events import AgentEvent
from onyx.agents.models import RunResult, RunSnapshot
from onyx.agents.runtime import Agent, Run, RunFailed, result_from_snapshot
from onyx.agents.tools import DEFAULT_AGENT_WAIT_SECONDS, AgentControl, SpawnResult
from onyx.agents.transcript import AgentRestorationConfig, RunStatus
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.models import Message
from onyx.utils.logger import setup_logger

logger = setup_logger()

MAX_LOADED_AGENTS = 64
MAX_CHILD_DEPTH = 8
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


class AgentCoordinator:
    """Own agent identities, loaded conversations, and their active or saved runs."""

    def __init__(
        self,
        *,
        agents: Sequence[AgentInfo] = (),
        lookup_agent: Callable[[str, str], AgentInfo | None] | None = None,
        resolve_agent: Callable[[str, str], Agent] | None = None,
        read_run: Callable[[str, str], RunSnapshot | None] | None = None,
    ) -> None:
        self._registrations = {info.id: info.model_copy(deep=True) for info in agents}
        if len(self._registrations) != len(agents):
            raise ValueError("Duplicate agent identity")
        self._agents: dict[str, Agent] = {}
        self._bindings: dict[str, RunCoordination] = {}
        self._latest: dict[str, RunSnapshot] = {}
        self._lookup_agent = lookup_agent
        self._resolve_agent = resolve_agent
        self._read_run = read_run
        self._closed = False
        # Registration and execution state change together under one lock.
        self._lock = threading.RLock()

    def register(self, info: AgentInfo) -> None:
        with self._lock:
            self.check_open()
            existing = self._registrations.get(info.id)
            if existing is not None and existing.parent_id != info.parent_id:
                raise ValueError("Agent registration changes its parent")
            self._registrations[info.id] = info.model_copy(deep=True)

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
        result: list[AgentInfo] = []
        for info in registrations:
            active = active_runs.get(info.id)
            saved = latest.get(info.id)
            if active is not None:
                result.append(
                    info.model_copy(
                        update={"latest_run_id": active.id, "status": active.status}
                    )
                )
            elif saved is not None:
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
            if self._closed:
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
            binding = RunCoordination(self, run, work, publish, cancellation)
            self._bindings[run.id] = binding
            return binding

    def close(self, timeout: float = DEFAULT_AGENT_WAIT_SECONDS) -> bool:
        if not 0 <= timeout <= OPERATION_TIMEOUT_SECONDS:
            raise ValueError("Close timeout is outside its allowed bounds")
        with self._lock:
            self._closed = True
            bindings = list(self._bindings.values())
        for binding in bindings:
            binding.run.cancel()
        deadline = time.monotonic() + timeout
        for binding in bindings:
            if not binding.run.wait_for_idle(
                timeout=max(0, deadline - time.monotonic())
            ):
                return False
        with self._lock:
            self._agents.clear()
            self._bindings.clear()
            self._latest.clear()
        return True

    def check_open(self) -> None:
        with self._lock:
            if self._closed:
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
            self._agents[agent.id] = agent
            return info

    def unregister_child(self, agent_id: str) -> None:
        with self._lock:
            self._agents.pop(agent_id)
            self._registrations.pop(agent_id)

    def loaded_child(self, agent_id: str, parent_id: str) -> Agent | None:
        with self._lock:
            info = self._registrations.get(agent_id)
            if info is not None and info.parent_id != parent_id:
                raise ValueError("Agent is not available to this parent")
            agent = self._agents.get(agent_id)
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
            binding = self._bindings.get(run_id)
            if binding is None:
                return None
            if self._registrations[binding.run.agent_id].parent_id != parent_id:
                raise ValueError("Run is not available to this parent")
            return binding.run

    def release(self, run: Run) -> None:
        snapshot = run.snapshot()
        with self._lock:
            if (
                self._registrations[run.agent_id].parent_id is not None
                and snapshot.status != RunStatus.RUNNING
            ):
                self._latest[run.agent_id] = snapshot
            self._bindings.pop(run.id, None)

    def _lookup(self, agent_id: str, parent_id: str) -> AgentInfo | None:
        with self._lock:
            info = self._registrations.get(agent_id)
        if info is None and self._lookup_agent is not None:
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
            if agent := self._agents.get(agent_id):
                return agent
            if len(self._agents) >= MAX_LOADED_AGENTS:
                raise ValueError("Loaded agent limit exceeded")
        if self._resolve_agent is None:
            raise ValueError("Agent restoration is unavailable")
        restored = self._resolve_agent(agent_id, parent_id)
        if restored.id != agent_id:
            raise ValueError("Restoration returned a different agent")
        with self._lock:
            self.check_open()
            if existing := self._agents.get(agent_id):
                return existing
            if len(self._agents) >= MAX_LOADED_AGENTS:
                raise ValueError("Loaded agent limit exceeded")
            self._agents[agent_id] = restored
        return restored

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
        record: RunSnapshot | None = saved
        if record is None and self._read_run is not None:
            if not load_archive:
                return None
            record = self._read_run(run_id, parent_id)
        if record is None:
            raise ValueError("Run history is unavailable")
        if record.run_id != run_id or record.agent_id is None:
            raise ValueError("Archive returned a different run")
        if self._lookup(record.agent_id, parent_id) is None:
            raise ValueError("Run is not available to this parent")
        return record


class _ChildExecution:
    def __init__(self, run: Run) -> None:
        self.run = run
        self.observed = False


class RunCoordination:
    """Own child runs and cancellation links for one parent execution."""

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
    ) -> Run:
        run = agent.start(
            messages=messages,
            max_steps=max_steps,
            coordinator=self.coordinator,
            cancellation=CancellationSignal(),
            parent_run_id=self.run.id,
            parent_tool_call_id=call_id,
            parent_message_id=message_id,
            inherited_event_sink=self.publish,
        )
        self.children[run.id] = _ChildExecution(run)
        self.work.tracker.started()
        run.add_idle_callback(self.work.tracker.finished)
        self._links.enter_context(self.cancellation.on_cancel(run.cancel))
        return run

    def finish(self, cancel: bool) -> list[RunSnapshot]:
        with self._lock:
            self._finished = True
            children = list(self.children.values())
        if cancel:
            for child in children:
                child.run.cancel()
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
    ) -> SpawnResult:
        with self.owner._lock:
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
                )
            except BaseException:
                coordinator.unregister_child(agent.id)
                raise
            return SpawnResult(agent_id=agent.id, agent_path=info.path, run_id=run.id)

    def start_run(
        self, agent_id: str, *, max_steps: int, messages: Sequence[Message]
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
        if previous is not None and previous.status != RunStatus.RUNNING:
            idle = self.owner.work.blocking(
                lambda: previous.wait_for_idle(timeout=OPERATION_TIMEOUT_SECONDS),
                self.owner.cancellation,
            )
            if not idle:
                raise TimeoutError("Previous agent execution is still draining")
        with self.owner._lock:
            self._check()
            return self.owner.start_child(
                agent,
                messages,
                max_steps,
                call_id=self.call_id,
                message_id=self.message_id,
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
        if latest is not None:
            return result_from_snapshot(latest)
        if timeout == 0:
            return None
        try:
            record = self.owner.work.blocking(
                lambda: coordinator.saved_run(run_id, self.owner.run.agent_id),
                self.owner.cancellation,
                timeout=timeout,
            )
        except TimeoutError:
            return None
        return result_from_snapshot(record)

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
        self.owner.work.blocking(
            lambda: self.owner.coordinator.saved_run(run_id, self.owner.run.agent_id),
            self.owner.cancellation,
        )

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
            return run.wait_for_idle(timeout)
        self.owner.coordinator.saved_run(run_id, self.owner.run.agent_id)
        return True

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
            run.add_idle_callback(callback)
            return
        self.owner.coordinator.saved_run(run_id, self.owner.run.agent_id)
        callback()
