"""Ephemeral conversation context for incognito chat turns.

USAGE_ONLY must carry the live conversation outside Postgres, so it lives in
Redis: one value per session, a sliding TTL that starts over on every save,
and explicit teardown when the chat closes. Keys are tenant-prefixed by the
Redis client. Redis may evict or expire the value mid-session: an expired
value loads as empty and the turn continues without earlier context.

Concurrent turns on one session are possible (the chat processing fence is a
status marker, not admission control), so save is a compare-and-set on a
version. A lost save means a concurrent writer won or the session ended, and
the caller must not retry with the history it loaded.
"""

from collections.abc import Collection
from uuid import UUID

from pydantic import BaseModel, TypeAdapter, ValidationError

from onyx.cache.interface import CacheBackendType
from onyx.chat.models import ChatMessageSimple
from onyx.chat.stream_buffer import stream_buffer_key_pattern
from onyx.configs import app_configs
from onyx.redis.redis_pool import get_redis_client
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
# 15 digits stay exact in a Lua double, and turn counts never approach it.
_MAX_VERSION_DIGITS = 15

_KEY_PREFIX = "incognito_ctx"

_MESSAGES_ADAPTER: TypeAdapter[list[ChatMessageSimple]] = TypeAdapter(
    list[ChatMessageSimple]
)

# Stored value grammar: ``<version>:<messages json>``. Lua and Python agree
# only on the digits-before-colon prefix, mirrored by _parse_version_prefix.
# Non-matching values read as version 0. Applies when stored version == ARGV[1].
_TOMBSTONE = b"tombstone"
_CAS_SCRIPT = """
local cur = redis.call('GET', KEYS[1])
if cur == 'tombstone' then
  return 0
end
local cur_version = 0
if cur then
  local v = string.match(cur, '^(%d+):')
  if v ~= nil and #v <= 15 then
    cur_version = tonumber(v)
  end
end
if cur_version ~= tonumber(ARGV[1]) then
  return 0
end
redis.call('SET', KEYS[1], ARGV[2], 'EX', tonumber(ARGV[3]))
return 1
"""


class IncognitoContext(BaseModel):
    """A session's history plus the version that makes save a compare-and-set."""

    version: int
    messages: list[ChatMessageSimple]


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
    """The value's version and JSON body, or (0, None) for a tombstone or a
    value this store did not write.

    Byte-for-byte the same rule as the CAS script: ASCII digits, at most
    ``_MAX_VERSION_DIGITS`` of them, immediately followed by a colon.
    """
    prefix, sep, body = raw.partition(b":")
    if sep and prefix.isdigit() and len(prefix) <= _MAX_VERSION_DIGITS:
        return int(prefix), body
    return 0, None


def load_incognito_context(chat_session_id: UUID) -> IncognitoContext:
    """The session's context, messages oldest first.

    Empty messages mean nothing was written, the session was torn down, the
    value expired, or its body failed to parse. The turn proceeds with whatever
    loads: missing context is degraded recall, never an error.
    """
    raw = _stored_context(chat_session_id)
    if raw is None:
        return IncognitoContext(version=0, messages=[])

    version, body = _parse_version_prefix(raw)
    if body is None:
        logger.warning(
            "Dropping unreadable incognito context for session %s", chat_session_id
        )
        return IncognitoContext(version=0, messages=[])
    try:
        messages = _MESSAGES_ADAPTER.validate_json(body)
    except ValidationError:
        # Corrupt context must end the session cleanly, not fail the turn.
        # Keeping the prefix version lets the next save overwrite the value.
        logger.warning(
            "Dropping unparseable incognito context for session %s", chat_session_id
        )
        return IncognitoContext(version=version, messages=[])
    return IncognitoContext(version=version, messages=messages)


def save_incognito_context(chat_session_id: UUID, context: IncognitoContext) -> bool:
    """Write the full history, bump the version, restart the idle clock.

    Applies only while the stored version still equals ``context.version``
    and the session has not been torn down. False means the write was
    discarded.

    Images are stripped: file bytes do not round-trip JSON, and incognito
    attachments only live within their own turn. Oldest messages fall off
    past the count and byte caps.
    """
    trimmed = [
        message.model_copy(update={"image_files": None, "image_token_count": 0})
        for message in context.messages[-_MAX_CONTEXT_MESSAGES:]
    ]
    body = _MESSAGES_ADAPTER.dump_json(trimmed)
    while len(body) > _MAX_CONTEXT_BYTES and len(trimmed) > 1:
        trimmed = trimmed[1:]
        body = _MESSAGES_ADAPTER.dump_json(trimmed)
    payload = f"{context.version + 1}:".encode() + body

    client = get_redis_client()
    result = client.eval(
        _CAS_SCRIPT,
        keys=[_context_key(chat_session_id)],
        args=[
            str(context.version).encode(),
            payload,
            str(INCOGNITO_CONTEXT_TTL_SECONDS).encode(),
        ],
    )
    return bool(result)


def append_incognito_message(chat_session_id: UUID, message: ChatMessageSimple) -> None:
    """Append one message to the session's live context, tolerating failure.

    A lost compare-and-set (a concurrent writer or an ended session) or a Redis
    blip must degrade the stored context, never fail the turn.
    Worst case the next turn is missing this message, which the load contract
    treats as ordinary missing context rather than an error.
    """
    try:
        context = load_incognito_context(chat_session_id)
        context.messages.append(message)
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
    buffered = list(client.scan_iter(match=stream_buffer_key_pattern(chat_session_id)))
    if buffered:
        client.delete(*buffered)
