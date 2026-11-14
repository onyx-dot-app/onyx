"""Bounded temporary history using the cache interface and session locks."""

import hashlib
import json
from collections import Counter
from collections.abc import Callable, Collection, Generator, Mapping, Sequence
from contextlib import contextmanager
from uuid import UUID

from pydantic import (
    TypeAdapter,
    ValidationError,
)

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import (
    CacheBackend,
    CacheBackendType,
    CacheLock,
    CacheLockLostError,
)
from onyx.chat.chat_processing_checker import ChatTurnAdmission
from onyx.chat.models import (
    IncognitoAgentResponse,
    IncognitoMessage,
    IncognitoState,
    PromptMetadata,
    ResponseRecord,
    serialize_incognito_message,
)
from onyx.chat.stream_buffer import stream_buffer_key_pattern
from onyx.configs import app_configs
from onyx.configs.chat_configs import (
    CHAT_STREAM_BUFFER_DONE_TTL_S,
    CHAT_STREAM_BUFFER_TTL_S,
)
from onyx.file_store.models import FileToolMetadata
from onyx.llm.models import Message, UserMessage
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
        if "format_version" not in state.model_fields_set:
            raise ValueError("Temporary history format lacks response ownership")
        if any(not key.isdigit() for key in state.responses):
            raise ValueError("Invalid response identity")
        return state
    except (ValidationError, ValueError, TypeError, KeyError):
        logger.warning("Dropping unreadable temporary history")
        return IncognitoState()


def load_incognito_context(chat_session_id: UUID) -> IncognitoState:
    cache = _cache()
    raw = cache.get(_context_key(chat_session_id))
    if raw is None:
        return IncognitoState()
    state = _decode_state(raw)
    return IncognitoState() if cache.exists(_tombstone_key(chat_session_id)) else state


def _retained_state(
    context: IncognitoState,
    *,
    required_messages: int = 1,
) -> IncognitoState:
    file_counts = Counter(
        message.metadata.file_id
        for message in context.messages
        if isinstance(message.metadata, PromptMetadata)
        and message.metadata.file_id is not None
    )
    retained_ids = {message.id for message in context.messages}
    state = IncognitoState(
        messages=list(context.messages),
        file_metadata={
            file_id: metadata
            for file_id, metadata in context.file_metadata.items()
            if file_id in file_counts
        },
        previous_run_id=context.previous_run_id,
        responses={
            key: record
            for key, record in context.responses.items()
            if not record.message_ids or record.message_ids[-1] in retained_ids
        },
    )
    response_keys = {
        record.message_ids[-1]: key
        for key, record in state.responses.items()
        if record.message_ids
    }
    if required_messages > _MAX_CONTEXT_MESSAGES:
        raise ValueError("Incognito input exceeds its message storage limit")
    size = len(state.model_dump_json().encode())
    while (
        size > _MAX_CONTEXT_BYTES or len(state.messages) > _MAX_CONTEXT_MESSAGES
    ) and len(state.messages) > required_messages:
        # Keep each question, its context messages, and all its responses together.
        remove_count = 0
        for index, message in enumerate(state.messages):
            if isinstance(message, UserMessage) and not _is_question_context(message):
                next_turn = input_group_start(state.messages, index)
                if next_turn > 0:
                    remove_count = next_turn
                    break
        if remove_count == 0:
            break
        if len(state.messages) - remove_count < required_messages:
            break
        removed = state.messages[:remove_count]
        del state.messages[:remove_count]
        size -= sum(len(_MESSAGE_ADAPTER.dump_json(message)) for message in removed)
        size -= len(removed) if state.messages else len(removed) - 1
        for message in removed:
            response_key = response_keys.get(message.id)
            if response_key is not None:
                record = state.responses.pop(response_key)
                size -= (
                    len(json.dumps(response_key).encode())
                    + 1
                    + len(record.model_dump_json().encode())
                )
                if state.responses:
                    size -= 1
            if not isinstance(message.metadata, PromptMetadata):
                continue
            file_id = message.metadata.file_id
            if file_id is None:
                continue
            file_counts[file_id] -= 1
            if file_counts[file_id] == 0 and file_id in state.file_metadata:
                metadata = state.file_metadata.pop(file_id)
                size -= (
                    len(json.dumps(file_id, ensure_ascii=False).encode())
                    + 1
                    + len(metadata.model_dump_json().encode())
                )
                if state.file_metadata:
                    size -= 1
    if size > _MAX_CONTEXT_BYTES or len(state.messages) > _MAX_CONTEXT_MESSAGES:
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
    admission: ChatTurnAdmission,
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
                # New inputs use this lock too, so a stale answer cannot follow them.
                admission.check_owner(chat_session_id)
                cache.set(
                    _context_key(chat_session_id),
                    payload,
                    ex=INCOGNITO_CONTEXT_TTL_SECONDS,
                )
                return True
        except _IncognitoLockError:
            logger.debug("Retrying incognito state write after lock contention or loss")
    return False


def _is_question_context(message: Message) -> bool:
    """An attachment or the SKILL.md of a mentioned skill: input that precedes
    its question."""
    return (
        isinstance(message, UserMessage)
        and isinstance(message.metadata, PromptMetadata)
        and (
            message.metadata.file_id is not None
            or message.metadata.skill_name is not None
        )
    )


def input_group_start(messages: Sequence[Message], question_index: int) -> int:
    """Find the attachment and skill messages immediately before a user question."""
    start = question_index
    while start > 0 and _is_question_context(messages[start - 1]):
        start -= 1
    return start


def save_incognito_user_messages(
    chat_session_id: UUID,
    messages: Sequence[Message],
    *,
    admission: ChatTurnAdmission,
    file_metadata: Mapping[str, FileToolMetadata] | None = None,
    history_message_ids: Sequence[str | None] | None = None,
) -> None:
    """Save the complete input, replacing its old group and response on regeneration."""
    if not messages or not isinstance(messages[-1], UserMessage):
        raise ValueError("Temporary input must end with a user question")
    question = messages[-1]
    if any(not isinstance(message, UserMessage) for message in messages):
        raise ValueError("Temporary input can contain only user messages")

    def update(state: IncognitoState | None) -> IncognitoState:
        context = state or IncognitoState()
        if history_message_ids is not None:
            selected = list(history_message_ids)
            if selected:
                retained: list[Message] = []
                for message in context.messages:
                    if message.id == selected[len(retained)]:
                        retained.append(message)
                        if len(retained) == len(selected):
                            break
                if len(retained) != len(selected):
                    raise ValueError(
                        "Selected temporary history changed before input was saved"
                    )
                context.messages = retained
                context.previous_run_id = next(
                    (
                        record.run_id
                        for record in context.responses.values()
                        if record.message_ids and record.message_ids[-1] == selected[-1]
                    ),
                    None,
                )
            else:
                context.messages = []
                context.previous_run_id = None
        if question.id is not None:
            for index, stored in enumerate(context.messages):
                if isinstance(stored, UserMessage) and stored.id == question.id:
                    start = input_group_start(context.messages, index)
                    context.messages = context.messages[:start]
                    context.previous_run_id = None
                    break
        context.messages.extend(messages)
        if file_metadata is not None:
            context.file_metadata = dict(file_metadata)
        return _retained_state(context, required_messages=len(messages))

    if not _update_incognito_state(chat_session_id, update, admission=admission):
        raise RuntimeError("Could not save temporary chat input")


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


def save_incognito_response(
    chat_session_id: UUID,
    response: ResponseRecord | None,
    *,
    admission: ChatTurnAdmission,
    message_id: int,
    messages: Sequence[Message],
) -> None:
    """Save the response replay in one value; reject conflicting retries."""
    messages = [
        message
        if message.id is not None
        else message.model_copy(update={"id": f"chat:{message_id}:output:{index}"})
        for index, message in enumerate(messages)
    ]
    replay = json.dumps(
        [serialize_incognito_message(message) for message in messages], sort_keys=True
    ).encode()
    digest = hashlib.sha256(replay)
    record = IncognitoAgentResponse(
        run_id=response.run_id if response is not None else None,
        checkpoint=response.checkpoint if response is not None else None,
        message_ids=[message.id for message in messages if message.id is not None],
        replay_digest="",
    )
    digest.update(record.model_dump_json(exclude={"replay_digest"}).encode())
    record.replay_digest = digest.hexdigest()
    response_key = str(message_id)
    already_saved = False

    def update(state: IncognitoState | None) -> IncognitoState | None:
        nonlocal already_saved
        already_saved = False
        if state is None:
            raise RuntimeError("Incognito session ended")
        if previous := state.responses.get(response_key):
            if previous.replay_digest != record.replay_digest:
                raise ValueError("Incognito response already has different content")
            already_saved = True
            return None
        context = state
        context.messages.extend(messages)
        if response is not None:
            context.previous_run_id = response.run_id
        context.responses = {**state.responses, response_key: record}
        return _retained_state(
            context,
            required_messages=len(messages),
        )

    if (
        not _update_incognito_state(
            chat_session_id,
            update,
            max_attempts=_MAX_COMMIT_ATTEMPTS,
            admission=admission,
        )
        and not already_saved
    ):
        raise RuntimeError("Incognito session ended or state lock is unavailable")
