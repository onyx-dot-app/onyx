"""Ephemeral conversation context for incognito chat turns.

USAGE_ONLY must carry the live conversation outside Postgres, so it lives in
Redis: one value per session, a sliding TTL that starts over on every save,
and explicit teardown when the chat closes. Keys are tenant-prefixed by the
Redis client. Redis may evict or expire the value mid-session: an expired
value loads as empty and the turn continues without earlier context.

Concurrent turns on one session are possible (the chat processing fence is a
status marker, not admission control), so save is a compare-and-set on a
version. A lost save means a concurrent writer won, and the caller must not
retry with the history it loaded.
"""

from uuid import UUID

from pydantic import BaseModel, TypeAdapter, ValidationError

from onyx.cache.interface import CacheBackendType
from onyx.chat.models import ChatMessageSimple
from onyx.configs import app_configs
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Sliding: restarted on every save, so context survives while the page stays
# active and dies within the hour once it goes idle or closes uncleanly.
INCOGNITO_CONTEXT_TTL_SECONDS = 3600
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
_CAS_SCRIPT = """
local cur = redis.call('GET', KEYS[1])
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


def _parse_version_prefix(raw: bytes) -> tuple[int, bytes | None]:
    """The value's version and JSON body, or (0, None) for a foreign value.

    Byte-for-byte the same rule as the CAS script: ASCII digits, at most
    ``_MAX_VERSION_DIGITS`` of them, immediately followed by a colon.
    """
    prefix, sep, body = raw.partition(b":")
    if sep and prefix.isdigit() and len(prefix) <= _MAX_VERSION_DIGITS:
        return int(prefix), body
    return 0, None


def load_incognito_context(chat_session_id: UUID) -> IncognitoContext:
    """The session's context, messages oldest first.

    Empty messages mean nothing was written, the value expired, or its body
    failed to parse. The turn proceeds with whatever loads: missing context
    is degraded recall, never an error.
    """
    raw = get_redis_client().get(_context_key(chat_session_id))
    if raw is None:
        return IncognitoContext(version=0, messages=[])

    version, body = _parse_version_prefix(raw)
    if body is None:
        logger.warning(
            "Dropping foreign incognito context for session %s", chat_session_id
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

    Applies only while the stored version still equals ``context.version``.
    False means a concurrent turn wrote first and this save was discarded.

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

    result = get_redis_client().eval(
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

    A lost compare-and-set (a concurrent turn) or a Redis blip must degrade the
    stored context, never fail the turn.
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


def teardown_incognito_session(chat_session_id: UUID) -> None:
    """Delete the session's context now rather than waiting out the TTL."""
    get_redis_client().delete(_context_key(chat_session_id))
