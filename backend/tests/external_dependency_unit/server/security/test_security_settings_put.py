"""Tests for the PUT /admin/security route handler.

Invokes ``put_security_settings_endpoint`` directly with a minimal Request
shim. Each test runs with a real Postgres-backed KV store and a real Redis
lock so the merge / serialization semantics are exercised end-to-end (sans
HTTP framing).
"""

import asyncio
import json
import threading
from collections.abc import Generator
from typing import Any
from typing import cast

import pytest
from fastapi import Request

from onyx.configs.constants import KV_SECURITY_SETTINGS_KEY
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.server.security import store as security_store
from onyx.server.security.api import put_security_settings_endpoint
from onyx.server.security.store import _build_env_defaults
from onyx.server.security.store import _install_cache_for_test
from onyx.server.security.store import invalidate_security_cache
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.constants import TEST_TENANT_ID


class _FakeRequest:
    """Minimal stand-in for fastapi.Request. The handler only awaits .body()."""

    def __init__(self, body_bytes: bytes) -> None:
        self._body = body_bytes

    async def body(self) -> bytes:
        return self._body


# The handler's `_: User` param is only present to wire the permission
# Depends; the body never reads it. Direct invocation bypasses Depends, so
# we pass a placeholder cast to User to satisfy the type checker.
_PLACEHOLDER_USER: User = cast(User, None)


def _put(body: dict[str, Any] | bytes) -> Any:
    """Invoke the PUT handler with the given JSON body or raw bytes."""
    raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    request = cast(Request, _FakeRequest(raw))
    return asyncio.run(put_security_settings_endpoint(request, _=_PLACEHOLDER_USER))


@pytest.fixture(autouse=True)
def _clean_kv_and_cache(
    tenant_context: None,  # noqa: ARG001 — requested for tenant-contextvar side effect
) -> Generator[None, None, None]:
    kv = get_kv_store()
    try:
        kv.delete(KV_SECURITY_SETTINGS_KEY)
    except KvKeyNotFoundError:
        pass
    invalidate_security_cache(TEST_TENANT_ID)
    import time as _time

    _install_cache_for_test(ttl=10.0, timer=_time.monotonic)
    yield
    try:
        kv.delete(KV_SECURITY_SETTINGS_KEY)
    except KvKeyNotFoundError:
        pass
    invalidate_security_cache(TEST_TENANT_ID)


# -----------------------------------------------------------------------------
# Single-tenant PUT semantics
# -----------------------------------------------------------------------------


def test_put_writes_only_explicit_fields() -> None:
    """Absent fields must not appear in the persisted KV blob."""
    _put({"user_directory_admin_only": True})

    stored = get_kv_store().load(KV_SECURITY_SETTINGS_KEY)
    assert stored == {"user_directory_admin_only": True}


def test_put_explicit_null_clears_previously_set_field() -> None:
    """An explicit null in PATCH semantics removes the key from KV."""
    _put({"user_directory_admin_only": True})
    assert get_kv_store().load(KV_SECURITY_SETTINGS_KEY) == {
        "user_directory_admin_only": True
    }

    _put({"user_directory_admin_only": None})
    stored = get_kv_store().load(KV_SECURITY_SETTINGS_KEY)
    assert stored == {}


def test_put_cross_field_validation_against_effective_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A payload that's individually valid but violates the merged invariant
    (min > max) must be rejected with INVALID_INPUT."""
    # Force env max length to 8 so payload's min=10 violates the post-merge
    # invariant even though the payload alone says nothing about max.
    from onyx.configs import app_configs

    monkeypatch.setattr(app_configs, "PASSWORD_MAX_LENGTH", 8, raising=False)

    with pytest.raises(OnyxError) as exc_info:
        _put({"password_min_length": 10})
    assert exc_info.value.error_code is OnyxErrorCode.INVALID_INPUT

    # Nothing should have been persisted.
    with pytest.raises(KvKeyNotFoundError):
        get_kv_store().load(KV_SECURITY_SETTINGS_KEY)


def test_put_accepts_password_min_length_zero() -> None:
    """``password_min_length=0`` is valid (matches env-parse behavior) and
    must not be coerced away by a truthy-fallback bug."""
    result = _put({"password_min_length": 0})
    assert result.password_min_length == 0

    stored = get_kv_store().load(KV_SECURITY_SETTINGS_KEY)
    assert stored == {"password_min_length": 0}


def test_put_extra_field_rejected_as_invalid_input() -> None:
    """extra='forbid' on the override model must surface as INVALID_INPUT."""
    with pytest.raises(OnyxError) as exc_info:
        _put({"this_field_does_not_exist": True})
    assert exc_info.value.error_code is OnyxErrorCode.INVALID_INPUT


def test_put_malformed_json_rejected_as_invalid_input() -> None:
    """Malformed JSON in the request body must map to INVALID_INPUT."""
    with pytest.raises(OnyxError) as exc_info:
        _put(b"{not valid json")
    assert exc_info.value.error_code is OnyxErrorCode.INVALID_INPUT


def test_put_non_object_body_rejected_as_invalid_input() -> None:
    """A JSON array (or any non-object) must map to INVALID_INPUT."""
    with pytest.raises(OnyxError) as exc_info:
        _put(b"[1, 2, 3]")
    assert exc_info.value.error_code is OnyxErrorCode.INVALID_INPUT


def test_put_single_tenant_allows_operator_locked_fields() -> None:
    """In single-tenant deployments, no fields are operator-locked."""
    result = _put({"password_min_length": 12, "mask_credential_prefix": False})
    assert result.password_min_length == 12
    assert result.mask_credential_prefix is False


# -----------------------------------------------------------------------------
# Multi-tenant operator-locked rejection
# -----------------------------------------------------------------------------


def test_put_multi_tenant_rejects_operator_locked_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Payload containing any operator-locked key returns
    INSUFFICIENT_PERMISSIONS in multi-tenant mode."""
    import shared_configs.contextvars as ctx

    monkeypatch.setattr(ctx, "MULTI_TENANT", True, raising=False)

    with pytest.raises(OnyxError) as exc_info:
        _put({"password_min_length": 12})
    assert exc_info.value.error_code is OnyxErrorCode.INSUFFICIENT_PERMISSIONS

    # Nothing should have been persisted.
    with pytest.raises(KvKeyNotFoundError):
        get_kv_store().load(KV_SECURITY_SETTINGS_KEY)


def test_put_multi_tenant_accepts_tenant_editable_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Payload with only tenant-editable keys succeeds in multi-tenant mode."""
    import shared_configs.contextvars as ctx

    monkeypatch.setattr(ctx, "MULTI_TENANT", True, raising=False)

    result = _put({"user_directory_admin_only": True})
    assert result.user_directory_admin_only is True

    stored = get_kv_store().load(KV_SECURITY_SETTINGS_KEY)
    assert stored == {"user_directory_admin_only": True}


# -----------------------------------------------------------------------------
# Concurrency: lock serializes writers, both disjoint writes land
# -----------------------------------------------------------------------------


def _put_in_thread(body: dict[str, Any], errors: list[BaseException]) -> None:
    """Worker that re-establishes the tenant contextvar (threads don't inherit
    it by default) and runs the PUT handler in its own event loop."""
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)
    try:
        _put(body)
    except BaseException as e:  # noqa: BLE001
        errors.append(e)
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


def test_concurrent_puts_disjoint_fields_both_land() -> None:
    """Two concurrent writers updating different keys must both persist."""
    errors: list[BaseException] = []
    t1 = threading.Thread(
        target=_put_in_thread,
        args=({"user_directory_admin_only": True}, errors),
    )
    t2 = threading.Thread(
        target=_put_in_thread,
        args=({"track_external_idp_expiry": True}, errors),
    )
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert errors == []
    stored = get_kv_store().load(KV_SECURITY_SETTINGS_KEY)
    assert stored == {
        "user_directory_admin_only": True,
        "track_external_idp_expiry": True,
    }


def test_concurrent_puts_under_invariant_pressure_never_corrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When two writers race on fields whose combination could violate the
    min<=max invariant, the lock serializes them and the later one is
    rejected by the post-merge validator. The KV blob must never reflect an
    invalid state."""
    # Pin env so that the natural defaults won't accidentally satisfy a bad
    # ordering of writes.
    from onyx.configs import app_configs

    monkeypatch.setattr(app_configs, "PASSWORD_MIN_LENGTH", 8, raising=False)
    monkeypatch.setattr(app_configs, "PASSWORD_MAX_LENGTH", 64, raising=False)

    errors: list[BaseException] = []
    t_min = threading.Thread(
        target=_put_in_thread,
        args=({"password_min_length": 20}, errors),
    )
    t_max = threading.Thread(
        target=_put_in_thread,
        args=({"password_max_length": 10}, errors),
    )
    t_min.start()
    t_max.start()
    t_min.join()
    t_max.join()

    # At least one write must have been rejected by the post-merge validator
    # (min=20 with max=10 violates the invariant). The first writer wins; the
    # second sees the now-merged state and is rejected.
    rejections = [
        e
        for e in errors
        if isinstance(e, OnyxError) and e.error_code is OnyxErrorCode.INVALID_INPUT
    ]
    assert len(rejections) == 1
    assert len(errors) == 1

    # The persisted blob must reflect exactly one of the two writes, with the
    # other field falling back to env defaults — never a min/max pair that
    # violates the invariant.
    stored: dict[str, Any] = {}
    try:
        loaded = get_kv_store().load(KV_SECURITY_SETTINGS_KEY)
    except KvKeyNotFoundError:
        loaded = None
    if isinstance(loaded, dict):
        stored = cast(dict[str, Any], loaded)

    env = _build_env_defaults()
    effective_min = stored.get("password_min_length", env.password_min_length)
    effective_max = stored.get("password_max_length", env.password_max_length)
    assert effective_min <= effective_max


# -----------------------------------------------------------------------------
# Storage-layer belt-and-braces (defense-in-depth)
# -----------------------------------------------------------------------------


def test_store_overrides_strips_operator_locked_in_multi_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even if the API check is bypassed, store_overrides itself must strip
    operator-locked fields when MULTI_TENANT=True."""
    import shared_configs.contextvars as ctx

    monkeypatch.setattr(ctx, "MULTI_TENANT", True, raising=False)

    from onyx.server.security.models import SecuritySettingsOverrides

    security_store.store_overrides(
        SecuritySettingsOverrides(
            user_directory_admin_only=True,
            password_min_length=12,  # operator-locked
            mask_credential_prefix=False,  # operator-locked
        )
    )

    stored = get_kv_store().load(KV_SECURITY_SETTINGS_KEY)
    assert stored == {"user_directory_admin_only": True}
