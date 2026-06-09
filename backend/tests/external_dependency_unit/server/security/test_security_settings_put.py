"""Tests for the PUT /admin/security route handler.

Invokes ``put_security_settings_endpoint`` directly with a minimal Request
shim. Each test runs against the real Postgres-backed singleton row plus a
real Redis lock so the merge / serialization semantics are exercised
end-to-end (sans HTTP framing).
"""

import asyncio
import json
import threading
from collections.abc import Generator
from typing import Any
from typing import cast

import pytest
from fastapi import Request
from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import SecuritySettings as SecuritySettingsRow
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.security import api as security_api
from onyx.server.security import store as security_store
from onyx.server.security.api import put_security_settings_endpoint
from onyx.server.security.models import SecuritySettingsOverrides
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


def _load_row_as_dict() -> dict[str, Any] | None:
    """Read the singleton row and return non-None columns as a dict.

    Mimics the prior ``KV_SECURITY_SETTINGS_KEY`` blob shape so existing test
    assertions can stay readable: only explicitly-set overrides appear. A
    missing row returns None.
    """
    with get_session_with_current_tenant() as session:
        row = session.execute(select(SecuritySettingsRow)).scalar_one_or_none()
    if row is None:
        return None
    overrides = SecuritySettingsOverrides.model_validate(row, from_attributes=True)
    return overrides.model_dump(exclude_none=True)


def _delete_security_settings_row() -> None:
    with get_session_with_current_tenant() as session:
        session.execute(delete(SecuritySettingsRow))
        session.commit()


@pytest.fixture(autouse=True)
def _clean_db_and_cache(
    db_session: Session,  # noqa: ARG001 — fixture requested only for its side-effect (SQL engine init); pytest binds by name
    tenant_context: None,  # noqa: ARG001 — requested for tenant-contextvar side effect
) -> Generator[None, None, None]:
    _delete_security_settings_row()
    invalidate_security_cache(TEST_TENANT_ID)
    import time as _time

    _install_cache_for_test(ttl=10.0, timer=_time.monotonic)
    yield
    _delete_security_settings_row()
    invalidate_security_cache(TEST_TENANT_ID)


# -----------------------------------------------------------------------------
# Single-tenant PUT semantics
# -----------------------------------------------------------------------------


def test_put_writes_only_explicit_fields() -> None:
    """Absent fields must not appear as non-null columns in the row."""
    _put({"user_directory_admin_only": True})

    assert _load_row_as_dict() == {"user_directory_admin_only": True}


def test_put_explicit_null_clears_previously_set_field() -> None:
    """An explicit null in PATCH semantics resets the column to NULL (= env)."""
    _put({"user_directory_admin_only": True})
    assert _load_row_as_dict() == {"user_directory_admin_only": True}

    _put({"user_directory_admin_only": None})
    # Row may still exist but every column is NULL → empty dict.
    assert _load_row_as_dict() == {}


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
    assert _load_row_as_dict() is None


def test_put_accepts_password_min_length_zero() -> None:
    """``password_min_length=0`` is valid (matches env-parse behavior) and
    must not be coerced away by a truthy-fallback bug."""
    result = _put({"password_min_length": 0})
    assert result.password_min_length == 0

    assert _load_row_as_dict() == {"password_min_length": 0}


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


def test_put_rejects_max_length_below_floor() -> None:
    """``password_max_length`` is floored at 4 (one char per required class).
    Anything lower is rejected up front instead of silently locking out every
    signup once all four require_* flags are on."""
    with pytest.raises(OnyxError) as exc_info:
        _put({"password_max_length": 3})
    assert exc_info.value.error_code is OnyxErrorCode.INVALID_INPUT
    # Nothing should have persisted — the validation runs after merge.
    assert _load_row_as_dict() is None


# -----------------------------------------------------------------------------
# Multi-tenant operator-locked rejection
# -----------------------------------------------------------------------------


def test_put_multi_tenant_rejects_operator_locked_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Payload containing any operator-locked key returns
    INSUFFICIENT_PERMISSIONS in multi-tenant mode."""
    monkeypatch.setattr(security_api, "MULTI_TENANT", True)
    monkeypatch.setattr(security_store, "MULTI_TENANT", True)

    with pytest.raises(OnyxError) as exc_info:
        _put({"password_min_length": 12})
    assert exc_info.value.error_code is OnyxErrorCode.INSUFFICIENT_PERMISSIONS

    # Nothing should have been persisted.
    assert _load_row_as_dict() is None


def test_put_multi_tenant_accepts_tenant_editable_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Payload with only tenant-editable keys succeeds in multi-tenant mode."""
    monkeypatch.setattr(security_api, "MULTI_TENANT", True)
    monkeypatch.setattr(security_store, "MULTI_TENANT", True)

    result = _put({"user_directory_admin_only": True})
    assert result.user_directory_admin_only is True

    assert _load_row_as_dict() == {"user_directory_admin_only": True}


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
    assert _load_row_as_dict() == {
        "user_directory_admin_only": True,
        "track_external_idp_expiry": True,
    }


def test_concurrent_puts_under_invariant_pressure_never_corrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When two writers race on fields whose combination could violate the
    min<=max invariant, the lock serializes them and the later one is
    rejected by the post-merge validator. The persisted row must never
    reflect an invalid state."""
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

    # The persisted state must reflect exactly one of the two writes, with the
    # other field falling back to env defaults — never a min/max pair that
    # violates the invariant.
    stored = _load_row_as_dict() or {}
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
    monkeypatch.setattr(security_store, "MULTI_TENANT", True)

    security_store.store_overrides(
        SecuritySettingsOverrides(
            user_directory_admin_only=True,
            password_min_length=12,  # operator-locked
            mask_credential_prefix=False,  # operator-locked
        )
    )

    assert _load_row_as_dict() == {"user_directory_admin_only": True}
