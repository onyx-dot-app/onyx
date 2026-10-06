import hashlib
import math
import re
import secrets
import time
from uuid import UUID

from pydantic import BaseModel, ValidationError

from onyx.auth.oauth_provider import (
    generate_oauth_provider_code,
    parse_oauth_provider_code_tenant,
)
from onyx.cache.factory import get_cache_backend, get_shared_cache_backend
from onyx.oauth_provider.models import (
    OAuthProviderConsentBinding,
    PendingOAuthProviderAuthorization,
    StoredOAuthProviderCode,
)

AUTHORIZATION_REQUEST_TTL_SECONDS = 10 * 60
AUTHORIZATION_CODE_TTL_SECONDS = 60

_HANDLE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
_REQUEST_KEY_PREFIX = "oauth_provider:request"
_CODE_KEY_PREFIX = "oauth_provider:code"


def _handle_digest(handle: str) -> str | None:
    if not _HANDLE_PATTERN.fullmatch(handle):
        return None
    return hashlib.sha256(handle.encode("ascii")).hexdigest()


def _request_keys(handle: str) -> tuple[str, str, str] | None:
    """Pending request and tenant claim (shared cache), consent binding (tenant cache)."""
    digest = _handle_digest(handle)
    if digest is None:
        return None
    return (
        f"{_REQUEST_KEY_PREFIX}:{digest}:pending",
        f"{_REQUEST_KEY_PREFIX}:{digest}:tenant",
        f"{_REQUEST_KEY_PREFIX}:{digest}:binding",
    )


def _code_key(code: str) -> str:
    return f"{_CODE_KEY_PREFIX}:{hashlib.sha256(code.encode('utf-8')).hexdigest()}"


def _loads_model[T: BaseModel](raw: bytes | None, model_type: type[T]) -> T | None:
    if raw is None:
        return None
    try:
        return model_type.model_validate_json(raw)
    except ValidationError:
        return None


def store_authorization_request(
    authorization: PendingOAuthProviderAuthorization,
) -> str:
    handle = secrets.token_urlsafe(32)
    pending_key, _, _ = _request_keys(handle) or (None, None, None)
    if pending_key is None:
        raise RuntimeError("Generated invalid OAuth provider authorization handle")
    if not get_shared_cache_backend().set_if_absent(
        pending_key,
        authorization.model_dump_json(),
        ex=AUTHORIZATION_REQUEST_TTL_SECONDS,
    ):
        raise RuntimeError("OAuth provider authorization handle collision")
    return handle


def get_authorization_request(handle: str) -> PendingOAuthProviderAuthorization | None:
    keys = _request_keys(handle)
    if keys is None:
        return None
    return _loads_model(
        get_shared_cache_backend().get(keys[0]), PendingOAuthProviderAuthorization
    )


def bind_authorization_request(
    handle: str,
    *,
    user_id: UUID,
    tenant_id: str,
    session_hash: str,
) -> OAuthProviderConsentBinding | None:
    keys = _request_keys(handle)
    if keys is None:
        return None
    pending_key, claim_key, binding_key = keys

    shared = get_shared_cache_backend()
    remaining_ttl = shared.ttl(pending_key)
    if remaining_ttl <= 0:
        return None
    # The pending request exists before sign-in, so it lives in the shared cache.
    # The first tenant to open its consent page claims it; everything that holds
    # user data stays in that tenant's cache.
    if (
        not shared.set_if_absent(claim_key, tenant_id, ex=remaining_ttl)
        and shared.get(claim_key) != tenant_id.encode()
    ):
        return None

    cache = get_cache_backend(tenant_id=tenant_id)
    binding = OAuthProviderConsentBinding(
        user_id=user_id,
        tenant_id=tenant_id,
        session_hash=session_hash,
        csrf_token=secrets.token_urlsafe(32),
    )
    if cache.set_if_absent(binding_key, binding.model_dump_json(), ex=remaining_ttl):
        return binding

    existing_binding = _loads_model(cache.get(binding_key), OAuthProviderConsentBinding)
    if existing_binding is None:
        return None
    if (
        existing_binding.user_id == user_id
        and existing_binding.tenant_id == tenant_id
        and existing_binding.session_hash == session_hash
    ):
        return existing_binding
    return None


def consume_authorization_request(
    handle: str,
    *,
    user_id: UUID,
    tenant_id: str,
    session_hash: str,
    csrf_token: str,
) -> PendingOAuthProviderAuthorization | None:
    keys = _request_keys(handle)
    if keys is None:
        return None
    pending_key, claim_key, binding_key = keys

    cache = get_cache_backend(tenant_id=tenant_id)
    binding = _loads_model(cache.get(binding_key), OAuthProviderConsentBinding)
    if (
        binding is None
        or binding.user_id != user_id
        or binding.tenant_id != tenant_id
        or binding.session_hash != session_hash
        or not secrets.compare_digest(binding.csrf_token.encode(), csrf_token.encode())
    ):
        return None
    shared = get_shared_cache_backend()
    # getdel on the shared request lets exactly one decision win.
    pending = _loads_model(
        shared.getdel(pending_key), PendingOAuthProviderAuthorization
    )
    cache.delete(binding_key)
    shared.delete(claim_key)
    return pending


def store_authorization_code(record: StoredOAuthProviderCode) -> str:
    seconds_until_expiry = record.expires_at - time.time()
    if seconds_until_expiry <= 0:
        raise ValueError("OAuth provider authorization code is already expired")
    if seconds_until_expiry > AUTHORIZATION_CODE_TTL_SECONDS:
        raise ValueError("OAuth provider authorization code expiry exceeds maximum TTL")
    code = generate_oauth_provider_code(record.tenant_id)
    if not get_cache_backend(tenant_id=record.tenant_id).set_if_absent(
        _code_key(code),
        record.model_dump_json(),
        ex=max(1, math.ceil(seconds_until_expiry)),
    ):
        raise RuntimeError("OAuth provider authorization code collision")
    return code


def get_authorization_code(code: str) -> StoredOAuthProviderCode | None:
    tenant_id = parse_oauth_provider_code_tenant(code)
    if tenant_id is None:
        return None
    record = _loads_model(
        get_cache_backend(tenant_id=tenant_id).get(_code_key(code)),
        StoredOAuthProviderCode,
    )
    if (
        record is None
        or record.tenant_id != tenant_id
        or record.expires_at <= time.time()
    ):
        return None
    return record


def consume_authorization_code(code: str) -> StoredOAuthProviderCode | None:
    tenant_id = parse_oauth_provider_code_tenant(code)
    if tenant_id is None:
        return None
    record = _loads_model(
        get_cache_backend(tenant_id=tenant_id).getdel(_code_key(code)),
        StoredOAuthProviderCode,
    )
    if (
        record is None
        or record.tenant_id != tenant_id
        or record.expires_at <= time.time()
    ):
        return None
    return record
