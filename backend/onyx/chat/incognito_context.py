"""Bounded temporary history using the cache interface and session locks."""

import hashlib
import json
from collections.abc import Callable, Collection, Generator, Sequence
from contextlib import contextmanager
from uuid import UUID

from pydantic import TypeAdapter, ValidationError

from onyx.agents.models import AgentInfo
from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import (
    CacheBackend,
    CacheBackendType,
    CacheLock,
    CacheLockLostError,
)
from onyx.chat.citation_processor import CitationMapping
from onyx.chat.models import (
    MAX_DISCOVERED_AGENTS,
    IncognitoAgentResponse,
    IncognitoAgentState,
    IncognitoContext,
    IncognitoMessage,
    IncognitoState,
    ResponseRecord,
    SavedAgentContext,
    serialize_incognito_message,
)
from onyx.chat.stream_buffer import stream_buffer_key_pattern
from onyx.configs import app_configs
from onyx.configs.chat_configs import (
    CHAT_STREAM_BUFFER_DONE_TTL_S,
    CHAT_STREAM_BUFFER_TTL_S,
)
from onyx.llm.models import Message, ToolResultMessage
from onyx.utils.logger import setup_logger

logger = setup_logger()

INCOGNITO_CONTEXT_TTL_SECONDS = 3600
_TOMBSTONE_TTL_SECONDS = max(
    INCOGNITO_CONTEXT_TTL_SECONDS,
    CHAT_STREAM_BUFFER_TTL_S,
    CHAT_STREAM_BUFFER_DONE_TTL_S,
)
_STATE_LOCK_SECONDS: float = 60.0
_STATE_LOCK_WAIT_SECONDS: float = 5.0
_MAX_CONTEXT_MESSAGES = 200
_MAX_CONTEXT_BYTES = 1_000_000
_MAX_TEARDOWNS_PER_RETRY = 100
_MAX_COMMIT_ATTEMPTS = 8
_KEY_PREFIX = "incognito_ctx:v2"
_PENDING_TEARDOWNS_KEY = f"{_KEY_PREFIX}:pending_teardowns"
_MESSAGE_ADAPTER = TypeAdapter(IncognitoMessage)


def incognito_context_available() -> bool:
    """Postgres cache must never receive USAGE_ONLY conversation content."""
    return app_configs.CACHE_BACKEND == CacheBackendType.REDIS


def _cache() -> CacheBackend:
    if not incognito_context_available():
        raise RuntimeError("Incognito history requires the Redis cache backend")
    return get_cache_backend()


def _context_key(chat_session_id: UUID) -> str:
    return f"{_KEY_PREFIX}:{chat_session_id}"


def _tombstone_key(chat_session_id: UUID) -> str:
    return f"{_context_key(chat_session_id)}:ended"


def _decode_state(raw: bytes) -> IncognitoState:
    try:
        if len(raw) > _MAX_CONTEXT_BYTES:
            raise ValueError("Temporary history exceeds its storage limit")
        state = IncognitoState.model_validate_json(raw)
        if any(not key.isdigit() for key in state.responses):
            raise ValueError("Invalid response identity")
        return state
    except (ValidationError, ValueError, TypeError, KeyError):
        logger.warning("Dropping unreadable temporary history")
        return IncognitoState()


def _read_state(cache: CacheBackend, chat_session_id: UUID) -> IncognitoState | None:
    raw = cache.get(_context_key(chat_session_id))
    if raw is None:
        return None
    state = _decode_state(raw)
    return None if cache.exists(_tombstone_key(chat_session_id)) else state


def _context(state: IncognitoState | None) -> IncognitoContext:
    if state is None:
        return IncognitoContext(version=0, messages=[])
    return IncognitoContext(
        version=state.version,
        messages=state.messages,
        previous_run_id=state.previous_run_id,
    )


def load_incognito_context(chat_session_id: UUID) -> IncognitoContext:
    return _context(_read_state(_cache(), chat_session_id))


def _retained_state(
    context: IncognitoContext,
    responses: dict[str, IncognitoAgentResponse],
    *,
    protected_response: str | None = None,
    required_messages: int = 1,
) -> IncognitoState:
    state = IncognitoState(
        version=context.version + 1,
        messages=context.messages[-_MAX_CONTEXT_MESSAGES:],
        previous_run_id=context.previous_run_id,
        responses=dict(responses),
    )
    required_messages = min(required_messages, len(state.messages))
    size = len(state.model_dump_json().encode())
    for key in sorted(state.responses, key=int):
        if size <= _MAX_CONTEXT_BYTES:
            break
        if key != protected_response:
            record = state.responses.pop(key)
            size -= (
                len(json.dumps(key).encode())
                + 1
                + len(record.model_dump_json().encode())
            )
            if state.responses:
                size -= 1
    while size > _MAX_CONTEXT_BYTES and len(state.messages) > required_messages:
        removed = state.messages.pop(0)
        size -= len(_MESSAGE_ADAPTER.dump_json(removed))
        if state.messages:
            size -= 1
    if size > _MAX_CONTEXT_BYTES:
        raise ValueError("Incognito response exceeds its storage limit")
    return state


class _IncognitoLockError(RuntimeError):
    """The session state lock could not be acquired or was lost."""


@contextmanager
def _locked_incognito_state(
    chat_session_id: UUID, *, blocking: bool = True
) -> Generator[tuple[CacheBackend, CacheLock], None, None]:
    cache = _cache()
    lock = cache.lock(
        f"{_context_key(chat_session_id)}:lock", timeout=_STATE_LOCK_SECONDS
    )
    if not lock.acquire(blocking=blocking, blocking_timeout=_STATE_LOCK_WAIT_SECONDS):
        raise _IncognitoLockError("Incognito state is busy")
    try:
        yield cache, lock
    finally:
        try:
            lock.release()
        except CacheLockLostError:
            logger.warning("Incognito state lock expired")


def _update_incognito_state(
    chat_session_id: UUID,
    update: Callable[[IncognitoState | None], IncognitoState | None],
    *,
    max_attempts: int = 1,
) -> bool:
    """Retry transformations against fresh state; never retry stale replacements."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    for _ in range(max_attempts):
        try:
            with _locked_incognito_state(chat_session_id) as (cache, lock):
                if cache.exists(_tombstone_key(chat_session_id)):
                    return False
                raw = cache.get(_context_key(chat_session_id))
                state = update(_decode_state(raw) if raw is not None else None)
                if state is None:
                    return False
                payload = state.model_dump_json().encode()
                if len(payload) > _MAX_CONTEXT_BYTES:
                    raise ValueError("Incognito response exceeds its storage limit")
                if not lock.owned():
                    raise _IncognitoLockError("Incognito state lock was lost")
                if cache.exists(_tombstone_key(chat_session_id)):
                    return False
                cache.set(
                    _context_key(chat_session_id),
                    payload,
                    ex=INCOGNITO_CONTEXT_TTL_SECONDS,
                )
                return True
        except _IncognitoLockError:
            logger.debug("Retrying incognito state write after lock contention or loss")
    return False


def save_incognito_context(chat_session_id: UUID, context: IncognitoContext) -> bool:
    """Replace only the root context version the caller read."""

    def update(state: IncognitoState | None) -> IncognitoState | None:
        current = state or IncognitoState()
        if current.version != context.version:
            return None
        return _retained_state(context, current.responses)

    return _update_incognito_state(chat_session_id, update)


def append_incognito_message(chat_session_id: UUID, message: Message) -> None:
    append_incognito_messages(chat_session_id, [message])


def append_incognito_messages(
    chat_session_id: UUID,
    messages: Sequence[Message],
    *,
    previous_run_id: str | None = None,
) -> None:
    """A failed temporary save degrades history without failing the turn."""
    try:
        context = load_incognito_context(chat_session_id)
        context.messages.extend(messages)
        if previous_run_id is not None:
            context.previous_run_id = previous_run_id
        if not save_incognito_context(chat_session_id, context):
            logger.warning(
                "Incognito context save lost its version for session %s",
                chat_session_id,
            )
    except Exception:
        # Serialization failures can include private message text in their exceptions.
        logger.error(
            "Failed to persist incognito context for session %s", chat_session_id
        )


def incognito_session_torn_down(chat_session_id: UUID) -> bool:
    return _cache().exists(_tombstone_key(chat_session_id))


def incognito_sessions_ended(chat_session_ids: Collection[UUID]) -> set[UUID]:
    if not chat_session_ids:
        return set()
    existing = _cache().exists_many(
        [
            key
            for session_id in chat_session_ids
            for key in (_tombstone_key(session_id), _context_key(session_id))
        ]
    )
    return {
        session_id
        for session_id in chat_session_ids
        if _tombstone_key(session_id) in existing
        or _context_key(session_id) not in existing
    }


def incognito_session_ended(chat_session_id: UUID) -> bool:
    return bool(incognito_sessions_ended([chat_session_id]))


def _finish_incognito_teardown(chat_session_id: UUID, *, blocking: bool = True) -> None:
    with _locked_incognito_state(chat_session_id, blocking=blocking) as (cache, lock):
        if not lock.owned():
            raise _IncognitoLockError("Incognito state lock was lost")
        cache.set(_tombstone_key(chat_session_id), 1, ex=_TOMBSTONE_TTL_SECONDS)
        cache.delete(_context_key(chat_session_id))
    cache.delete_prefix(stream_buffer_key_pattern(chat_session_id).removesuffix("*"))
    cache.set_remove(_PENDING_TEARDOWNS_KEY, str(chat_session_id))


def teardown_incognito_session(chat_session_id: UUID) -> None:
    """Fence access immediately and retain failed cleanup for worker retries."""
    cache = _cache()
    # Register before fencing so a busy session or failed cleanup remains discoverable.
    cache.set_add(_PENDING_TEARDOWNS_KEY, str(chat_session_id))
    cache.set(_tombstone_key(chat_session_id), 1, ex=_TOMBSTONE_TTL_SECONDS)
    try:
        _finish_incognito_teardown(chat_session_id)
    except _IncognitoLockError:
        try:
            _enqueue_incognito_teardown_retry()
        except Exception:
            logger.exception("Could not enqueue incognito teardown retry")


def retry_incognito_teardowns() -> None:
    """Retry a bounded batch without waiting for busy sessions."""
    if not incognito_context_available():
        return
    cache = _cache()
    for member in cache.set_members(
        _PENDING_TEARDOWNS_KEY, limit=_MAX_TEARDOWNS_PER_RETRY
    ):
        session_id = UUID(member.decode())
        try:
            _finish_incognito_teardown(session_id, blocking=False)
        except _IncognitoLockError:
            logger.debug("Incognito cleanup deferred for busy session %s", session_id)
        except Exception:
            logger.exception("Incognito teardown retry failed for %s", session_id)


def _enqueue_incognito_teardown_retry() -> None:
    from onyx.background.celery.versioned_apps.client import app
    from onyx.configs.constants import OnyxCeleryTask
    from shared_configs.contextvars import get_current_tenant_id

    app.send_task(
        OnyxCeleryTask.CHECK_FOR_INCOGNITO_FILE_CLEANUP,
        kwargs={"tenant_id": get_current_tenant_id()},
        countdown=_STATE_LOCK_SECONDS,
        expires=600,
    )


def _incognito_records(
    chat_session_id: UUID, visible_message_ids: Sequence[int]
) -> list[IncognitoAgentState]:
    if not visible_message_ids:
        return []
    state = _read_state(_cache(), chat_session_id)
    if state is None:
        return []
    return [
        agent
        for message_id in reversed(visible_message_ids)
        if (response := state.responses.get(str(message_id))) is not None
        for agent in response.agents
    ]


def _incognito_metadata(records: list[IncognitoAgentState]) -> dict[str, AgentInfo]:
    by_id: dict[str, IncognitoAgentState] = {}
    for agent in records:
        by_id.pop(agent.agent_id, None)
        by_id[agent.agent_id] = agent
    return {
        agent_id: AgentInfo(
            id=agent_id,
            path=agent.agent_path,
            parent_id=agent.parent_agent_id,
            description=agent.description,
            restoration_config=agent.configuration,
            latest_run_id=agent.responses[-1].run_id if agent.responses else None,
            status=agent.responses[-1].status if agent.responses else None,
        )
        for agent_id, agent in by_id.items()
    }


def load_incognito_agent_metadata(
    chat_session_id: UUID, visible_message_ids: Sequence[int]
) -> list[AgentInfo]:
    metadata = _incognito_metadata(
        _incognito_records(chat_session_id, visible_message_ids)
    )
    selected: dict[str, AgentInfo] = {}
    for info in list(metadata.values())[-MAX_DISCOVERED_AGENTS:]:
        selected[info.id] = info
        parent_id = info.parent_id
        while (
            parent_id is not None
            and parent_id in metadata
            and parent_id not in selected
        ):
            parent = metadata[parent_id]
            selected[parent_id] = parent
            parent_id = parent.parent_id
    return sorted(selected.values(), key=lambda info: info.path.count("/"))


def lookup_incognito_agent(
    chat_session_id: UUID,
    visible_message_ids: Sequence[int],
    agent_id: str,
    parent_id: str,
) -> AgentInfo | None:
    metadata = _incognito_metadata(
        _incognito_records(chat_session_id, visible_message_ids)
    )
    info = metadata.get(agent_id)
    return info if info and info.parent_id == parent_id else None


def load_incognito_agent_history(
    chat_session_id: UUID, visible_message_ids: Sequence[int], agent_id: str
) -> SavedAgentContext:
    records = [
        agent
        for agent in _incognito_records(chat_session_id, visible_message_ids)
        if agent.agent_id == agent_id
    ]
    if not records:
        raise ValueError("Agent is not visible on the selected incognito branch")
    latest = records[-1]
    by_id = {run.run_id: run for record in records for run in record.responses}
    selected: list[ResponseRecord] = []
    visited: set[str] = set()
    run_id = latest.responses[-1].run_id if latest.responses else None
    while run_id is not None:
        if run_id in visited:
            raise ValueError("Incognito agent history contains a cycle")
        visited.add(run_id)
        run = by_id.get(run_id)
        if run is None:
            raise ValueError("Incognito agent history expired and cannot be resumed")
        selected.append(run)
        run_id = run.previous_run_id
    sources: CitationMapping = {}
    for record in records:
        if any(run.run_id in visited for run in record.responses):
            sources.update(record.sources)
    return SavedAgentContext(
        agent_id=latest.agent_id,
        configuration=latest.configuration,
        messages=[
            message
            for response in reversed(selected)
            for message in [
                *response.input_messages,
                *response.messages,
            ]
        ],
        checkpoint=selected[0].checkpoint if selected else None,
        previous_run_id=selected[0].run_id if selected else None,
        sources=sources,
    )


def load_incognito_saved_run(
    chat_session_id: UUID,
    visible_message_ids: Sequence[int],
    run_id: str,
    parent_id: str,
) -> ResponseRecord | None:
    records = _incognito_records(chat_session_id, visible_message_ids)
    metadata = _incognito_metadata(records)
    for agent in records:
        if metadata[agent.agent_id].parent_id != parent_id:
            continue
        for run in agent.responses:
            if run.run_id == run_id:
                return run
    return None


def _response_records(
    response: ResponseRecord | None,
    sources_by_run: dict[str, CitationMapping],
    replay_digest: str,
) -> IncognitoAgentResponse:
    records = IncognitoAgentResponse(replay_digest=replay_digest)
    local: dict[str, IncognitoAgentState] = {}

    def append(run: ResponseRecord, parent_id: str | None = None) -> None:
        if run.agent_id is None:
            raise ValueError("Temporary agent runs require agent and run identities")
        saved = local.get(run.agent_id)
        if saved is None:
            saved = IncognitoAgentState(
                agent_id=run.agent_id,
                agent_path=run.agent_path,
                parent_agent_id=parent_id,
                description=run.agent_description,
                configuration=run.restoration_config,
                responses=[],
            )
            records.agents.append(saved)
            local[run.agent_id] = saved
        if any(item.run_id == run.run_id for item in saved.responses):
            raise ValueError("Duplicate temporary agent run")
        response = run.model_copy(deep=True, update={"child_runs": []})
        # Temporary history retains model content; sources are stored separately.
        for message in [*response.input_messages, *response.messages]:
            if isinstance(message, ToolResultMessage):
                message.details = None
        saved.responses.append(response)
        saved.sources.update(sources_by_run.get(run.run_id, {}))
        for child in run.child_runs:
            append(child, run.agent_id)

    if response is not None:
        if response.agent_id is None:
            raise ValueError("Temporary responses require an agent identity")
        for child in response.child_runs:
            append(child, response.agent_id)
    return records


def save_incognito_response(
    chat_session_id: UUID,
    response: ResponseRecord | None,
    sources_by_run: dict[str, CitationMapping],
    *,
    message_id: int,
    messages: Sequence[Message],
) -> None:
    """Save root and child replay in one value; reject conflicting retries."""
    replay = json.dumps(
        [serialize_incognito_message(message) for message in messages], sort_keys=True
    ).encode()
    digest = hashlib.sha256(replay)
    if response is not None:
        digest.update(response.run_id.encode())
    record = _response_records(response, sources_by_run, digest.hexdigest())
    response_key = str(message_id)
    already_saved = False

    def update(state: IncognitoState | None) -> IncognitoState | None:
        nonlocal already_saved
        already_saved = False
        if state is None:
            raise RuntimeError("Incognito session ended")
        if previous := state.responses.get(response_key):
            if previous.model_dump_json() != record.model_dump_json():
                raise ValueError("Incognito response already has different content")
            already_saved = True
            return None
        context = _context(state)
        context.messages.extend(messages)
        if response is not None:
            context.previous_run_id = response.run_id
        responses = {**state.responses, response_key: record}
        return _retained_state(
            context,
            responses,
            protected_response=response_key,
            required_messages=len(messages),
        )

    if (
        not _update_incognito_state(
            chat_session_id, update, max_attempts=_MAX_COMMIT_ATTEMPTS
        )
        and not already_saved
    ):
        raise RuntimeError("Incognito session ended or state lock is unavailable")
