"""Optional, caller-owned agent discovery and execution coordination."""

import asyncio
import threading
import time
from collections.abc import Callable, Sequence
from contextlib import ExitStack

from pydantic import BaseModel, ConfigDict

from onyx.agents.concurrency import (
    CLEANUP_SECONDS,
    OPERATION_TIMEOUT_SECONDS,
    ExecutionServices,
    WorkTracker,
)
from onyx.agents.events import AgentEvent
from onyx.agents.models import RunResult, RunSnapshot
from onyx.agents.runtime import Agent, Run, RunFailed, result_from_snapshot
from onyx.agents.tools import DEFAULT_AGENT_WAIT_SECONDS, AgentControl, SpawnResult
from onyx.agents.transcript import AgentConfiguration, AgentTranscript, RunStatus
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
    restoration_config: AgentConfiguration | None
    latest_run_id: str | None = None
    status: RunStatus | None = None


class AgentCoordinator:
    def __init__(
        self,
        *,
        agents: Sequence[AgentInfo] = (),
        lookup_agent: Callable[[str, str], AgentInfo | None] | None = None,
        resolve_agent: Callable[[str, str], Agent] | None = None,
        read_run: Callable[[str, str], AgentTranscript | None] | None = None,
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
        self._lock = threading.RLock()

    def register(self, info: AgentInfo) -> None:
        with self._lock:
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
        with self._lock:
            result: list[AgentInfo] = []
            active_runs = {
                binding.run.agent_id: binding.run for binding in self._bindings.values()
            }
            for info in self._registrations.values():
                if info.parent_id != parent_id:
                    continue
                active = active_runs.get(info.id)
                latest = self._latest.get(info.id)
                if active is not None:
                    result.append(
                        info.model_copy(
                            update={"latest_run_id": active.id, "status": active.status}
                        )
                    )
                elif latest is not None:
                    result.append(
                        info.model_copy(
                            update={
                                "latest_run_id": latest.run_id,
                                "status": latest.status,
                            }
                        )
                    )
                else:
                    result.append(info.model_copy(deep=True))
            return result

    def bind(
        self,
        run: Run,
        services: ExecutionServices,
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
            binding = RunCoordination(self, run, services, publish, cancellation)
            self._bindings[run.id] = binding
            return binding

    async def close(self, timeout: float = DEFAULT_AGENT_WAIT_SECONDS) -> bool:
        if not 0 <= timeout <= OPERATION_TIMEOUT_SECONDS:
            raise ValueError("Close timeout is outside its allowed bounds")
        with self._lock:
            self._closed = True
            bindings = list(self._bindings.values())
        for binding in bindings:
            binding.run.cancel()
        deadline = time.monotonic() + timeout
        for binding in bindings:
            if not await binding.run.wait_for_idle(
                timeout=max(0, deadline - time.monotonic())
            ):
                return False
        with self._lock:
            self._agents.clear()
            self._bindings.clear()
            self._latest.clear()
        return True

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

    def _resolve(self, agent_id: str, parent_id: str) -> Agent:
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
            if existing := self._agents.get(agent_id):
                return existing
            if len(self._agents) >= MAX_LOADED_AGENTS:
                raise ValueError("Loaded agent limit exceeded")
            self._agents[agent_id] = restored
        return restored

    def _saved(self, run_id: str, parent_id: str) -> RunSnapshot | AgentTranscript:
        with self._lock:
            saved = next(
                (item for item in self._latest.values() if item.run_id == run_id), None
            )
        record: RunSnapshot | AgentTranscript | None = saved
        if record is None and self._read_run is not None:
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
    def __init__(
        self,
        coordinator: AgentCoordinator,
        run: Run,
        services: ExecutionServices,
        publish: Callable[[AgentEvent], None],
        cancellation: CancellationSignal,
    ) -> None:
        self.coordinator = coordinator
        self.run = run
        self.services = services
        self.publish = publish
        self.cancellation = cancellation
        self.children: dict[str, _ChildExecution] = {}
        self._links = ExitStack()
        self._archive_work = WorkTracker()
        self._finished = False

    def for_tool(
        self, call_id: str, parent_message_id: str, active: threading.Event
    ) -> AgentControl:
        return _ToolControl(self, call_id, parent_message_id, active)

    async def finish(self, cancel: bool) -> list[RunSnapshot]:
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
                    await child.run.wait(timeout=max(0, deadline - time.monotonic()))
                except RunFailed as error:
                    if not child.observed and not cancel and failure is None:
                        failure = error
                except AgentCancelled:
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

    def add_idle_callback(self, callback: Callable[[], None]) -> None:
        children = tuple(self.children.values())
        pending = WorkTracker()
        for _ in range(len(children) + 1):
            pending.started()
        self._archive_work.on_idle(pending.finished)
        for child in children:
            child.run.add_idle_callback(pending.finished)

        pending.on_idle(callback)

    def release(self) -> None:
        with self.coordinator._lock:
            if self.coordinator._registrations[self.run.agent_id].parent_id is not None:
                self.coordinator._latest[self.run.agent_id] = self.run.snapshot()
            self.coordinator._bindings.pop(self.run.id, None)
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
        if asyncio.get_running_loop() is not self.owner.services.loop:
            raise RuntimeError("Coordination requires its owning event loop")
        if (
            not self.active.is_set()
            or self.owner._finished
            or self.owner.coordinator._closed
        ):
            raise RuntimeError("Coordination requires an active tool invocation")

    def discovery(self) -> list[AgentInfo]:
        self._check()
        return self.owner.coordinator.discovery(self.owner.run.agent_id)

    async def spawn_agent(
        self,
        agent: Agent,
        *,
        name: str,
        description: str,
        max_steps: int,
        messages: Sequence[Message],
        restoration_config: AgentConfiguration | None = None,
    ) -> SpawnResult:
        self._check()
        if not name or "/" in name:
            raise ValueError("Agent name must be a nonempty label without slashes")
        coordinator = self.owner.coordinator
        with coordinator._lock:
            parent = coordinator._registrations[self.owner.run.agent_id]
            depth = 0
            ancestor = parent
            while ancestor.parent_id is not None:
                depth += 1
                ancestor = coordinator._registrations[ancestor.parent_id]
            if depth >= MAX_CHILD_DEPTH:
                raise ValueError("Agent nesting limit exceeded")
            if (
                agent.id in coordinator._registrations
                or len(coordinator._agents) >= MAX_LOADED_AGENTS
            ):
                raise ValueError(
                    "Agent already registered or loaded agent limit exceeded"
                )
            info = AgentInfo(
                id=agent.id,
                path=f"{parent.path}/{name}",
                parent_id=parent.id,
                description=description,
                restoration_config=restoration_config,
            )
            coordinator.register(info)
            coordinator._agents[agent.id] = agent
        try:
            run = self._start(agent, messages, max_steps)
        except BaseException:
            with coordinator._lock:
                coordinator._agents.pop(agent.id)
                coordinator._registrations.pop(agent.id)
            raise
        return SpawnResult(agent_id=agent.id, agent_path=info.path, run_id=run.id)

    def _start(self, agent: Agent, messages: Sequence[Message], max_steps: int) -> Run:
        run = agent.start(
            messages=messages,
            max_steps=max_steps,
            coordinator=self.owner.coordinator,
            execution_services=self.owner.services,
            cancellation=CancellationSignal(),
            parent_run_id=self.owner.run.id,
            parent_tool_call_id=self.call_id,
            parent_message_id=self.message_id,
            inherited_event_sink=self.owner.publish,
        )
        self.owner.children[run.id] = _ChildExecution(run)
        self.owner._links.enter_context(self.owner.cancellation.on_cancel(run.cancel))
        return run

    async def start_run(
        self, agent_id: str, *, max_steps: int, messages: Sequence[Message]
    ) -> str:
        self._check()
        coordinator = self.owner.coordinator
        with coordinator._lock:
            agent = coordinator._agents.get(agent_id)
            info = coordinator._registrations.get(agent_id)
            if info is not None and info.parent_id != self.owner.run.agent_id:
                raise ValueError("Agent is not available to this parent")
        if agent is None:
            if coordinator._resolve_agent is None:
                raise ValueError("Agent restoration is unavailable")
            agent = await self.owner.services.blocking(
                lambda: coordinator._resolve(agent_id, self.owner.run.agent_id),
                self.owner.cancellation,
                tracker=self.owner._archive_work,
            )
        self._check()
        with coordinator._lock:
            previous = next(
                (
                    binding.run
                    for binding in reversed(list(coordinator._bindings.values()))
                    if binding.run.agent_id == agent_id
                ),
                None,
            )
        if previous is not None and previous.status != RunStatus.RUNNING:
            waiting = asyncio.create_task(
                previous.wait_for_idle(timeout=OPERATION_TIMEOUT_SECONDS)
            )
            with self.owner.cancellation.on_cancel(
                lambda: self.owner.services.loop.call_soon_threadsafe(waiting.cancel)
            ):
                try:
                    idle = await waiting
                except asyncio.CancelledError:
                    self._check()
                    raise
            if not idle:
                raise TimeoutError("Previous agent execution is still draining")
        self._check()
        return self._start(agent, messages, max_steps).id

    def _local(self, run_id: str) -> Run | None:
        coordinator = self.owner.coordinator
        with coordinator._lock:
            binding = coordinator._bindings.get(run_id)
            if binding is None:
                return None
            info = coordinator._registrations[binding.run.agent_id]
            if info.parent_id != self.owner.run.agent_id:
                raise ValueError("Run is not available to this parent")
            return binding.run

    async def wait_run(
        self, run_id: str, *, timeout: float = DEFAULT_AGENT_WAIT_SECONDS
    ) -> RunResult | None:
        self._check()
        if not 0 <= timeout <= OPERATION_TIMEOUT_SECONDS:
            raise ValueError("Wait timeout is outside its allowed bounds")
        child = self.owner.children.get(run_id)
        run = child.run if child else self._local(run_id)
        if run is not None:
            try:
                result = await run.wait(timeout=timeout)
            except TimeoutError:
                return None
            except (RunFailed, AgentCancelled):
                if child is not None:
                    child.observed = True
                raise
            if child is not None:
                child.observed = True
            return result
        coordinator = self.owner.coordinator
        with coordinator._lock:
            latest = next(
                (
                    record
                    for record in coordinator._latest.values()
                    if record.run_id == run_id
                ),
                None,
            )
            if latest is not None:
                if latest.agent_id is None:
                    raise ValueError("Saved run has no agent identity")
                info = coordinator._registrations[latest.agent_id]
                if info.parent_id != self.owner.run.agent_id:
                    raise ValueError("Run is not available to this parent")
        if latest is not None:
            return result_from_snapshot(latest)
        if timeout == 0:
            if coordinator._read_run is None:
                raise ValueError("Run history is unavailable")
            return None
        deadline = asyncio.timeout(timeout)
        try:
            async with deadline:
                record = await self.owner.services.blocking(
                    lambda: coordinator._saved(run_id, self.owner.run.agent_id),
                    self.owner.cancellation,
                    tracker=self.owner._archive_work,
                )
        except TimeoutError:
            if deadline.expired():
                return None
            raise
        return result_from_snapshot(
            RunSnapshot.model_validate(record, from_attributes=True)
        )

    async def cancel_run(self, run_id: str) -> None:
        self._check()
        child = self.owner.children.get(run_id)
        run = child.run if child else self._local(run_id)
        if run is not None:
            run.cancel()
            return
        await self.owner.services.blocking(
            lambda: self.owner.coordinator._saved(run_id, self.owner.run.agent_id),
            self.owner.cancellation,
            tracker=self.owner._archive_work,
        )
