import hashlib
import json
import math
import re
import secrets
import time
from collections.abc import Awaitable
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ValidationError

from onyx.mcp_oauth.models import (
    MCPOAuthConsentBinding,
    PendingMCPOAuthAuthorization,
    StoredMCPOAuthCode,
)
from onyx.redis.redis_pool import get_async_redis_connection
from shared_configs.configs import DEFAULT_REDIS_PREFIX

AUTHORIZATION_REQUEST_TTL_SECONDS = 10 * 60
AUTHORIZATION_CODE_TTL_SECONDS = 60

_HANDLE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
_KEY_PREFIX = f"{DEFAULT_REDIS_PREFIX}:mcp_oauth"
_REQUEST_KEY_PREFIX = f"{_KEY_PREFIX}:request"
_CODE_KEY_PREFIX = f"{_KEY_PREFIX}:code"
_RATE_KEY_PREFIX = f"{_KEY_PREFIX}:rate"

_CONSUME_REQUEST_SCRIPT = """
if redis.call("GET", KEYS[2]) ~= ARGV[1] then
  return nil
end
local pending = redis.call("GET", KEYS[1])
if not pending then
  return nil
end
redis.call("DEL", KEYS[1], KEYS[2])
return pending
"""

_RATE_LIMIT_SCRIPT = """
local count = redis.call("INCR", KEYS[1])
if count == 1 then
  redis.call("EXPIRE", KEYS[1], ARGV[1])
end
return count <= tonumber(ARGV[2])
"""


def _new_handle() -> str:
    return secrets.token_urlsafe(32)


def _handle_digest(handle: str) -> str | None:
    if not _HANDLE_PATTERN.fullmatch(handle):
        return None
    return hashlib.sha256(handle.encode("ascii")).hexdigest()


def _request_keys(handle: str) -> tuple[str, str] | None:
    digest = _handle_digest(handle)
    if digest is None:
        return None
    tag = f"{{{digest}}}"
    return (
        f"{_REQUEST_KEY_PREFIX}:{tag}:pending",
        f"{_REQUEST_KEY_PREFIX}:{tag}:binding",
    )


def _code_key(code: str) -> str | None:
    digest = _handle_digest(code)
    if digest is None:
        return None
    return f"{_CODE_KEY_PREFIX}:{{{digest}}}"


def _rate_key(bucket: str, window_seconds: int) -> str:
    digest = hashlib.sha256(bucket.encode("utf-8")).hexdigest()
    window_id = int(time.time() // window_seconds)
    return f"{_RATE_KEY_PREFIX}:{{{digest}}}:{window_id}"


def _loads_model[T: BaseModel](raw: object, model_type: type[T]) -> T | None:
    if not isinstance(raw, (str, bytes, bytearray)):
        return None
    try:
        return model_type.model_validate(json.loads(raw))
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError, ValidationError):
        return None


async def store_authorization_request(
    authorization: PendingMCPOAuthAuthorization,
) -> str:
    handle = _new_handle()
    pending_key, _ = _request_keys(handle) or (None, None)
    if pending_key is None:
        raise RuntimeError("Generated invalid MCP OAuth authorization handle")

    redis = await get_async_redis_connection()
    was_stored = await redis.set(
        pending_key,
        authorization.model_dump_json(),
        ex=AUTHORIZATION_REQUEST_TTL_SECONDS,
        nx=True,
    )
    if not was_stored:
        raise RuntimeError("MCP OAuth authorization handle collision")
    return handle


async def get_authorization_request(
    handle: str,
) -> PendingMCPOAuthAuthorization | None:
    keys = _request_keys(handle)
    if keys is None:
        return None

    redis = await get_async_redis_connection()
    return _loads_model(await redis.get(keys[0]), PendingMCPOAuthAuthorization)


async def bind_authorization_request(
    handle: str,
    *,
    user_id: UUID,
    tenant_id: str,
    session_hash: str,
) -> MCPOAuthConsentBinding | None:
    keys = _request_keys(handle)
    if keys is None:
        return None
    pending_key, binding_key = keys

    redis = await get_async_redis_connection()
    remaining_ttl_ms = await redis.pttl(pending_key)
    if remaining_ttl_ms <= 0:
        return None

    binding = MCPOAuthConsentBinding(
        user_id=user_id,
        tenant_id=tenant_id,
        session_hash=session_hash,
        csrf_token=_new_handle(),
    )
    raw_binding = binding.model_dump_json()
    was_bound = await redis.set(
        binding_key,
        raw_binding,
        px=remaining_ttl_ms,
        nx=True,
    )
    if was_bound:
        return binding

    existing_binding = _loads_model(
        await redis.get(binding_key), MCPOAuthConsentBinding
    )
    if existing_binding is None:
        return None
    if (
        existing_binding.user_id == user_id
        and existing_binding.tenant_id == tenant_id
        and existing_binding.session_hash == session_hash
    ):
        return existing_binding
    return None


async def consume_authorization_request(
    handle: str,
    *,
    user_id: UUID,
    tenant_id: str,
    session_hash: str,
    csrf_token: str,
) -> PendingMCPOAuthAuthorization | None:
    keys = _request_keys(handle)
    if keys is None:
        return None
    pending_key, binding_key = keys

    redis = await get_async_redis_connection()
    raw_binding = await redis.get(binding_key)
    binding = _loads_model(raw_binding, MCPOAuthConsentBinding)
    if binding is None:
        return None
    if (
        binding.user_id != user_id
        or binding.tenant_id != tenant_id
        or binding.session_hash != session_hash
        or not secrets.compare_digest(binding.csrf_token.encode(), csrf_token.encode())
    ):
        return None
    if not isinstance(raw_binding, (str, bytes, bytearray)):
        return None

    raw_pending = await cast(
        Awaitable[object],
        redis.eval(
            _CONSUME_REQUEST_SCRIPT,
            2,
            pending_key,
            binding_key,
            raw_binding,
        ),
    )
    return _loads_model(raw_pending, PendingMCPOAuthAuthorization)


def _validate_code_expiry(expires_at: float) -> int:
    now = time.time()
    seconds_until_expiry = expires_at - now
    if seconds_until_expiry <= 0:
        raise ValueError("MCP OAuth authorization code is already expired")
    if seconds_until_expiry > AUTHORIZATION_CODE_TTL_SECONDS:
        raise ValueError("MCP OAuth authorization code expiry exceeds maximum TTL")
    return max(1, math.ceil(seconds_until_expiry))


def _stored_code_is_active(record: StoredMCPOAuthCode) -> bool:
    return record.expires_at > time.time()


async def store_authorization_code(record: StoredMCPOAuthCode) -> str:
    ttl_seconds = _validate_code_expiry(record.expires_at)
    code = _new_handle()
    key = _code_key(code)
    if key is None:
        raise RuntimeError("Generated invalid MCP OAuth authorization code")

    redis = await get_async_redis_connection()
    was_stored = await redis.set(
        key,
        record.model_dump_json(),
        ex=ttl_seconds,
        nx=True,
    )
    if not was_stored:
        raise RuntimeError("MCP OAuth authorization code collision")
    return code


async def get_authorization_code(code: str) -> StoredMCPOAuthCode | None:
    key = _code_key(code)
    if key is None:
        return None

    redis = await get_async_redis_connection()
    record = _loads_model(await redis.get(key), StoredMCPOAuthCode)
    if record is None or not _stored_code_is_active(record):
        return None
    return record


async def consume_authorization_code(code: str) -> StoredMCPOAuthCode | None:
    key = _code_key(code)
    if key is None:
        return None

    redis = await get_async_redis_connection()
    record = _loads_model(await redis.getdel(key), StoredMCPOAuthCode)
    if record is None or not _stored_code_is_active(record):
        return None
    return record


async def allow_mcp_oauth_request(
    bucket: str,
    *,
    limit: int,
    window_seconds: int,
) -> bool:
    if limit <= 0:
        raise ValueError("MCP OAuth rate limit must be positive")
    if window_seconds <= 0:
        raise ValueError("MCP OAuth rate-limit window must be positive")

    redis = await get_async_redis_connection()
    allowed = await cast(
        Awaitable[object],
        redis.eval(
            _RATE_LIMIT_SCRIPT,
            1,
            _rate_key(bucket, window_seconds),
            str(window_seconds),
            str(limit),
        ),
    )
    return bool(allowed)
