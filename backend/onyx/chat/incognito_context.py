"""Bounded temporary replay state, committed atomically within tenant Redis."""

import hashlib
import json
from collections.abc import Collection, Sequence
from typing import cast
from uuid import UUID

from pydantic import BaseModel, Field, JsonValue, TypeAdapter, ValidationError
from redis.exceptions import WatchError

from onyx.agents.models import AgentInfo
from onyx.cache.interface import CacheBackendType
from onyx.chat.citation_processor import CitationMapping
from onyx.chat.llm_step import PromptMetadata, prompt_metadata
from onyx.chat.models import MAX_DISCOVERED_AGENTS, ResponseRecord, SavedAgentContext
from onyx.chat.stream_buffer import stream_buffer_key_pattern
from onyx.configs import app_configs
from onyx.configs.constants import MessageType
from onyx.deep_research.models import ResearchConfiguration
from onyx.llm.models import (
    AnyThinkingBlock,
    AssistantMessage,
    Message,
    SystemMessage,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.tenant_redis_client import TenantRedisPipeline
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Sliding: restarted on every save, so context survives while the page stays
# active and dies within the hour once it goes idle or closes uncleanly.
INCOGNITO_CONTEXT_TTL_SECONDS = 3600
# Long enough that an in-flight turn cannot resurrect a torn-down context.
_TOMBSTONE_TTL_SECONDS = INCOGNITO_CONTEXT_TTL_SECONDS
# Raw-storage caps. Token budgeting trims context further at prompt build.
# These only bound what one session may hold in Redis.
_MAX_CONTEXT_MESSAGES = 200
_MAX_CONTEXT_BYTES = 1_000_000
_MAX_VERSION_DIGITS = 15
_MAX_COMMIT_ATTEMPTS = 8
_ROOT_ID_FIELD = b"root_id"
_PREVIOUS_RUN_FIELD = b"previous_run_id"

_KEY_PREFIX = "incognito_ctx"

_MESSAGE_ADAPTER: TypeAdapter[Message] = TypeAdapter(Message)
_STORED_MESSAGES_ADAPTER = TypeAdapter(list[dict[str, JsonValue]])


class _LegacyToolCall(BaseModel):
    tool_call_id: str
    tool_name: str
    tool_arguments: dict[str, JsonValue]


class _LegacyMessage(BaseModel):
    """Read Redis records written before canonical agent messages."""

    message: str
    message_type: MessageType
    token_count: int
    tool_calls: list[_LegacyToolCall] | None = None
    tool_call_id: str | None = None
    thinking_blocks: list[AnyThinkingBlock] | None = None
    file_id: str | None = None
    should_cache: bool = False


def _read_message(item: dict[str, JsonValue]) -> Message:
    if "role" in item:
        data = dict(item)
        metadata = PromptMetadata.model_validate(data.pop("metadata", {}))
        message = _MESSAGE_ADAPTER.validate_python(data)
        message.metadata = metadata
        return message
    legacy = _LegacyMessage.model_validate(item)
    metadata = PromptMetadata(
        token_count=legacy.token_count,
        file_id=legacy.file_id,
        should_cache=legacy.should_cache,
        is_reminder=legacy.message_type == MessageType.USER_REMINDER,
    )
    if legacy.message_type in (MessageType.USER, MessageType.USER_REMINDER):
        return UserMessage(content=legacy.message, metadata=metadata)
    if legacy.message_type == MessageType.SYSTEM:
        return SystemMessage(content=legacy.message, metadata=metadata)
    if legacy.message_type == MessageType.TOOL_CALL_RESPONSE:
        return ToolResultMessage(
            content=legacy.message,
            tool_call_id=legacy.tool_call_id or "",
            tool_name="",
            metadata=metadata,
        )
    if legacy.message_type == MessageType.ASSISTANT:
        return AssistantMessage(
            content=[
                *(
                    [ThinkingContent(text="", blocks=legacy.thinking_blocks)]
                    if legacy.thinking_blocks
                    else []
                ),
                TextContent(text=legacy.message),
                *(
                    ToolCall(
                        id=call.tool_call_id,
                        name=call.tool_name,
                        arguments=call.tool_arguments,
                    )
                    for call in legacy.tool_calls or []
                ),
            ],
            metadata=metadata,
        )
    raise ValueError("Unsupported stored message role")


def _write_message(message: Message) -> dict[str, JsonValue]:
    data: dict[str, JsonValue] = message.model_dump(mode="json", exclude={"details"})
    data["metadata"] = prompt_metadata(message).model_dump(
        exclude={"image_files", "image_token_count"}
    )
    return data


_TOMBSTONE = b"tombstone"


class IncognitoContext(BaseModel):
    """A session's history plus the version that makes save a compare-and-set."""

    version: int
    messages: list[Message]
    previous_run_id: str | None = None


def incognito_context_available() -> bool:
    """Whether this deployment can hold incognito context at all.

    USAGE_ONLY content must never reach Postgres, so the Postgres cache
    backend (Lite) means the feature is absent rather than degraded.
    """
    return app_configs.CACHE_BACKEND == CacheBackendType.REDIS


def _context_key(chat_session_id: UUID) -> str:
    return f"{_KEY_PREFIX}:{chat_session_id}"


def _stored_context(chat_session_id: UUID) -> bytes | None:
    return get_redis_client().get(_context_key(chat_session_id))


def _parse_version_prefix(raw: bytes) -> tuple[int, bytes | None]:
    """Read the version prefix without accepting unbounded integer input."""
    prefix, sep, body = raw.partition(b":")
    if sep and prefix.isdigit() and len(prefix) <= _MAX_VERSION_DIGITS:
        return int(prefix), body
    return 0, None


def load_incognito_context(chat_session_id: UUID) -> IncognitoContext:
    """Read root replay state and its predecessor from one Redis transaction."""
    with get_redis_client().pipeline() as pipeline:
        pipeline.get(_context_key(chat_session_id))
        pipeline.hget(_agents_key(chat_session_id), _PREVIOUS_RUN_FIELD)
        # Redis pipelines return untyped results in queued command order.
        raw, previous_run = cast(list[bytes | None], pipeline.execute())
    return _decode_context(chat_session_id, raw, previous_run)


def _decode_context(
    chat_session_id: UUID, raw: bytes | None, previous_run: bytes | None
) -> IncognitoContext:
    if raw is None:
        return IncognitoContext(version=0, messages=[])

    version, body = _parse_version_prefix(raw)
    if body is None:
        logger.warning(
            "Dropping unreadable incognito context for session %s", chat_session_id
        )
        return IncognitoContext(version=0, messages=[])
    try:
        decoded = _STORED_MESSAGES_ADAPTER.validate_json(body)
        messages = [_read_message(item) for item in decoded]
    except (ValidationError, ValueError, TypeError, KeyError):
        # Corrupt context must end the session cleanly, not fail the turn.
        # Keeping the prefix version lets the next save overwrite the value.
        logger.warning(
            "Dropping unparseable incognito context for session %s", chat_session_id
        )
        return IncognitoContext(version=version, messages=[])
    return IncognitoContext(
        version=version,
        messages=messages,
        previous_run_id=previous_run.decode() if previous_run else None,
    )


class _IncognitoWrite(BaseModel):
    context: bytes
    agents: dict[bytes, bytes]


def _retained_state(
    context: IncognitoContext,
    agents: dict[bytes, bytes],
    *,
    protected_response: bytes | None = None,
    required_messages: int = 1,
) -> _IncognitoWrite:
    retained = dict(agents)
    retained.pop(b"bytes", None)
    retained.pop(_PREVIOUS_RUN_FIELD, None)
    if context.previous_run_id is not None:
        retained[_PREVIOUS_RUN_FIELD] = context.previous_run_id.encode()
    messages = [
        _write_message(message) for message in context.messages[-_MAX_CONTEXT_MESSAGES:]
    ]
    required_messages = min(required_messages, len(messages))
    removable = sorted(
        (key for key in retained if key.isdigit() and key != protected_response),
        key=int,
    )
    payload = f"{context.version + 1}:".encode() + json.dumps(messages).encode()
    size = len(payload) + sum(len(key) + len(value) for key, value in retained.items())
    for key in removable:
        if size <= _MAX_CONTEXT_BYTES:
            break
        size -= len(key) + len(retained.pop(key))
    while size > _MAX_CONTEXT_BYTES and len(messages) > required_messages:
        old_size = len(payload)
        messages = messages[1:]
        payload = f"{context.version + 1}:".encode() + json.dumps(messages).encode()
        size += len(payload) - old_size
    if size > _MAX_CONTEXT_BYTES:
        raise ValueError("Incognito response exceeds its storage limit")
    return _IncognitoWrite(context=payload, agents=retained)


def _queue_write(
    pipeline: TenantRedisPipeline, chat_session_id: UUID, state: _IncognitoWrite
) -> None:
    pipeline.multi()
    pipeline.set(
        _context_key(chat_session_id), state.context, ex=INCOGNITO_CONTEXT_TTL_SECONDS
    )
    pipeline.delete(_agents_key(chat_session_id))
    if state.agents:
        pipeline.hset(_agents_key(chat_session_id), state.agents)
        pipeline.expire(_agents_key(chat_session_id), INCOGNITO_CONTEXT_TTL_SECONDS)


def save_incognito_context(chat_session_id: UUID, context: IncognitoContext) -> bool:
    """Replace the expected root context and apply the shared storage bound."""
    with get_redis_client().pipeline() as pipeline:
        pipeline.watch(_context_key(chat_session_id), _agents_key(chat_session_id))
        raw = pipeline.get_watched(_context_key(chat_session_id))
        if raw == _TOMBSTONE:
            return False
        version = _parse_version_prefix(raw)[0] if raw is not None else 0
        if version != context.version:
            return False
        agents = pipeline.hgetall_watched(_agents_key(chat_session_id))
        state = _retained_state(context, agents)
        _queue_write(pipeline, chat_session_id, state)
        try:
            pipeline.execute()
        except WatchError:
            return False
    return True


def append_incognito_message(chat_session_id: UUID, message: Message) -> None:
    append_incognito_messages(chat_session_id, [message])


def append_incognito_messages(
    chat_session_id: UUID,
    messages: Sequence[Message],
    *,
    previous_run_id: str | None = None,
) -> None:
    """Append one message to the session's live context, tolerating failure.

    A lost compare-and-set (a concurrent writer or an ended session) or a Redis
    blip must degrade the stored context, never fail the turn.
    Worst case the next turn is missing this message, which the load contract
    treats as ordinary missing context rather than an error.
    """
    try:
        context = load_incognito_context(chat_session_id)
        context.messages.extend(messages)
        if previous_run_id is not None:
            context.previous_run_id = previous_run_id
        if not save_incognito_context(chat_session_id, context):
            logger.warning(
                "Incognito context save lost the CAS for session %s", chat_session_id
            )
    except Exception:
        logger.exception(
            "Failed to persist incognito context for session %s", chat_session_id
        )


def incognito_session_torn_down(chat_session_id: UUID) -> bool:
    """Whether this session's teardown tombstone is still present.

    A session holds no context until its first message, so absence is not an
    answer. Callers deciding whether to accept new work must use this.
    """
    return _stored_context(chat_session_id) == _TOMBSTONE


def incognito_sessions_ended(chat_session_ids: Collection[UUID]) -> set[UUID]:
    """Which of these sessions have no live context, by teardown or by expiry.

    One round trip for the whole batch. Duplicate ids collapse in the result.
    """
    # Materialized once: the ids and the values are zipped positionally, so a
    # set argument must not be iterated twice.
    session_ids = list(chat_session_ids)
    values = get_redis_client().mget(
        [_context_key(session_id) for session_id in session_ids]
    )
    return {
        session_id
        for session_id, raw in zip(session_ids, values, strict=True)
        if raw is None or raw == _TOMBSTONE
    }


def incognito_session_ended(chat_session_id: UUID) -> bool:
    """Whether the live context is gone, by teardown or by expiry.

    Absence counts, so a session that has not written its first message reads
    as ended. Only for callers that have already ruled that out.
    """
    return bool(incognito_sessions_ended([chat_session_id]))


def teardown_incognito_session(chat_session_id: UUID) -> None:
    """End the session now: tombstone the context so an in-flight turn cannot
    recreate it (a missing key reads as version zero), and delete the buffered
    stream chunks holding the streamed answer NDJSON."""
    client = get_redis_client()
    client.set(_context_key(chat_session_id), _TOMBSTONE, ex=_TOMBSTONE_TTL_SECONDS)
    client.delete(_agents_key(chat_session_id))
    buffered = list(client.scan_iter(match=stream_buffer_key_pattern(chat_session_id)))
    if buffered:
        client.delete(*buffered)


def _agents_key(chat_session_id: UUID) -> str:
    return f"{_KEY_PREFIX}:{chat_session_id}:agents"


def _read_agent_fields(
    chat_session_id: UUID, message_ids: Sequence[int]
) -> list[bytes | None]:
    if _stored_context(chat_session_id) in (None, _TOMBSTONE):
        return [None] * len(message_ids)
    return get_redis_client().hmget(
        _agents_key(chat_session_id),
        [str(message_id) for message_id in message_ids],
    )


class _IncognitoAgent(BaseModel):
    parent_agent_id: str | None = None
    agent_id: str
    agent_path: str
    description: str
    configuration: ResearchConfiguration | None
    responses: list[ResponseRecord]
    sources: CitationMapping = Field(default_factory=dict)


class IncognitoAgentResponse(BaseModel):
    replay_digest: str
    agents: list[_IncognitoAgent] = Field(default_factory=list)


def _incognito_records(
    chat_session_id: UUID, visible_message_ids: Sequence[int]
) -> list[_IncognitoAgent]:
    if not visible_message_ids:
        return []
    return [
        agent
        for raw in reversed(_read_agent_fields(chat_session_id, visible_message_ids))
        if raw is not None
        for agent in IncognitoAgentResponse.model_validate_json(raw).agents
    ]


def _incognito_metadata(records: list[_IncognitoAgent]) -> dict[str, AgentInfo]:
    by_id: dict[str, _IncognitoAgent] = {}
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


def get_or_create_incognito_root_id(
    chat_session_id: UUID, proposed_agent_id: str
) -> str:
    for _ in range(_MAX_COMMIT_ATTEMPTS):
        with get_redis_client().pipeline() as pipeline:
            pipeline.watch(_context_key(chat_session_id), _agents_key(chat_session_id))
            raw = pipeline.get_watched(_context_key(chat_session_id))
            if raw is None or raw == _TOMBSTONE:
                raise RuntimeError("Incognito session ended")
            agents = pipeline.hgetall_watched(_agents_key(chat_session_id))
            if root_id := agents.get(_ROOT_ID_FIELD):
                return root_id.decode()
            agents[_ROOT_ID_FIELD] = proposed_agent_id.encode()
            context = _decode_context(
                chat_session_id, raw, agents.get(_PREVIOUS_RUN_FIELD)
            )
            state = _retained_state(context, agents)
            _queue_write(pipeline, chat_session_id, state)
            try:
                pipeline.execute()
            except WatchError:
                continue
            return proposed_agent_id
    raise RuntimeError("Incognito context changed repeatedly during registration")


def _response_records(
    response: ResponseRecord | None,
    sources_by_run: dict[str, CitationMapping],
    replay_digest: str,
) -> IncognitoAgentResponse:
    records = IncognitoAgentResponse(replay_digest=replay_digest)
    local: dict[str, _IncognitoAgent] = {}

    def append(run: ResponseRecord, parent_id: str | None = None) -> None:
        if run.agent_id is None:
            raise ValueError("Temporary agent runs require agent and run identities")
        saved = local.get(run.agent_id)
        if saved is None:
            saved = _IncognitoAgent(
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
        saved.responses.append(run.model_copy(deep=True, update={"child_runs": []}))
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
    """Atomically save replay, evicting old records before old root messages.
    Evicted child histories cannot resume; oversized responses leave both stores unchanged.
    """
    # Detect conflicting retries without keeping another copy of root output.
    replay = json.dumps(
        [_write_message(message) for message in messages], sort_keys=True
    ).encode()
    digest = hashlib.sha256(replay)
    if response is not None:
        digest.update(response.run_id.encode())
    body = (
        _response_records(response, sources_by_run, digest.hexdigest())
        .model_dump_json()
        .encode()
    )
    response_key = str(message_id).encode()
    for _ in range(_MAX_COMMIT_ATTEMPTS):
        with get_redis_client().pipeline() as pipeline:
            pipeline.watch(_context_key(chat_session_id), _agents_key(chat_session_id))
            raw = pipeline.get_watched(_context_key(chat_session_id))
            if raw is None or raw == _TOMBSTONE:
                raise RuntimeError("Incognito session ended")
            agents = pipeline.hgetall_watched(_agents_key(chat_session_id))
            if previous := agents.get(response_key):
                if previous != body:
                    raise ValueError("Incognito response already has different content")
                return
            context = _decode_context(
                chat_session_id, raw, agents.get(_PREVIOUS_RUN_FIELD)
            )
            context.messages.extend(messages)
            if response is not None:
                context.previous_run_id = response.run_id
            agents[response_key] = body
            state = _retained_state(
                context,
                agents,
                protected_response=response_key,
                required_messages=len(messages),
            )
            _queue_write(pipeline, chat_session_id, state)
            try:
                pipeline.execute()
            except WatchError:
                continue
            return
    raise RuntimeError("Incognito context changed repeatedly during response save")
