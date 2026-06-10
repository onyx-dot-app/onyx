"""PUT /admin/security tests.

Invokes the handler directly with a Request shim — exercises merge and
lock-serialization semantics against the real DB + Redis lock without HTTP
framing.
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
    """Stand-in for fastapi.Request — the handler only awaits ``.body()``."""

    def __init__(self, body_bytes: bytes) -> None:
        self._body = body_bytes

    async def body(self) -> bytes:
        return self._body


# The `_: User` Depends param is unread; direct invocation bypasses Depends.
_PLACEHOLDER_USER: User = cast(User, None)


def _put(body: dict[str, Any] | bytes) -> Any:
    raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    request = cast(Request, _FakeRequest(raw))
    return asyncio.run(put_security_settings_endpoint(request, _=_PLACEHOLDER_USER))


def _load_row_as_dict() -> dict[str, Any] | None:
    """Singleton row as a dict of only explicitly-set overrides, or None."""
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
    db_session: Session,  # noqa: ARG001 — requested for side-effect (SQL engine init)
    tenant_context: None,  # noqa: ARG001 — requested for side-effect (tenant contextvar)
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
    """Explicit null clears the column to NULL (loader falls back to env)."""
    _put({"user_directory_admin_only": True})
    assert _load_row_as_dict() == {"user_directory_admin_only": True}

    _put({"user_directory_admin_only": None})
    # Row exists but every column is NULL → empty dict after exclude_none.
    assert _load_row_as_dict() == {}


def test_put_cross_field_validation_against_effective_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A payload that's individually valid but violates the merged invariant
    (min > max) must be rejected with INVALID_INPUT."""
    from onyx.configs import app_configs

    # Force env max=8 so payload min=10 violates after merge.
    monkeypatch.setattr(app_configs, "PASSWORD_MAX_LENGTH", 8, raising=False)

    with pytest.raises(OnyxError) as exc_info:
        _put({"password_min_length": 10})
    assert exc_info.value.error_code is OnyxErrorCode.INVALID_INPUT

    assert _load_row_as_dict() is None


def test_put_accepts_password_min_length_zero() -> None:
    """``password_min_length=0`` is valid; the merge must not coerce it
    away via a truthy fallback."""
    result = _put({"password_min_length": 0})
    assert result.password_min_length == 0

    assert _load_row_as_dict() == {"password_min_length": 0}


def test_put_extra_field_rejected_as_invalid_input() -> None:
    with pytest.raises(OnyxError) as exc_info:
        _put({"this_field_does_not_exist": True})
    assert exc_info.value.error_code is OnyxErrorCode.INVALID_INPUT


def test_put_malformed_json_rejected_as_invalid_input() -> None:
    with pytest.raises(OnyxError) as exc_info:
        _put(b"{not valid json")
    assert exc_info.value.error_code is OnyxErrorCode.INVALID_INPUT


def test_put_non_object_body_rejected_as_invalid_input() -> None:
    with pytest.raises(OnyxError) as exc_info:
        _put(b"[1, 2, 3]")
    assert exc_info.value.error_code is OnyxErrorCode.INVALID_INPUT


def test_put_single_tenant_allows_operator_locked_fields() -> None:
    """In single-tenant deployments, no fields are operator-locked."""
    result = _put({"password_min_length": 12, "mask_credential_prefix": False})
    assert result.password_min_length == 12
    assert result.mask_credential_prefix is False


def test_put_rejects_max_length_below_floor() -> None:
    """``password_max_length`` is floored at PASSWORD_MAX_LENGTH_FLOOR."""
    with pytest.raises(OnyxError) as exc_info:
        _put({"password_max_length": 3})
    assert exc_info.value.error_code is OnyxErrorCode.INVALID_INPUT
    assert _load_row_as_dict() is None


# -----------------------------------------------------------------------------
# Multi-tenant operator-locked rejection
# -----------------------------------------------------------------------------


def test_put_multi_tenant_rejects_operator_locked_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An operator-locked key in payload returns INSUFFICIENT_PERMISSIONS."""
    monkeypatch.setattr(security_api, "MULTI_TENANT", True)
    monkeypatch.setattr(security_store, "MULTI_TENANT", True)

    with pytest.raises(OnyxError) as exc_info:
        _put({"password_min_length": 12})
    assert exc_info.value.error_code is OnyxErrorCode.INSUFFICIENT_PERMISSIONS

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
    # Threads don't inherit contextvars; re-establish before the PUT.
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
    """Two writers racing on fields whose combination could break the
    min<=max invariant: the lock serializes them and the post-merge
    validator rejects the loser. Persisted state is never invalid.
    """
    from onyx.configs import app_configs

    # Pin env so natural defaults don't accidentally satisfy a bad ordering.
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

    # Exactly one writer wins; the other sees the merged state and is rejected.
    rejections = [
        e
        for e in errors
        if isinstance(e, OnyxError) and e.error_code is OnyxErrorCode.INVALID_INPUT
    ]
    assert len(rejections) == 1
    assert len(errors) == 1

    stored = _load_row_as_dict() or {}
    env = _build_env_defaults()
    effective_min = stored.get("password_min_length", env.password_min_length)
    effective_max = stored.get("password_max_length", env.password_max_length)
    assert effective_min <= effective_max


# -----------------------------------------------------------------------------
# Storage-layer belt-and-braces (defense-in-depth)
# -----------------------------------------------------------------------------


def test_apply_patch_strips_operator_locked_in_multi_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Belt-and-braces: the write itself strips operator-locked fields in
    multi-tenant, even if a future caller bypasses the API-layer rejection.
    """
    monkeypatch.setattr(security_store, "MULTI_TENANT", True)

    security_store.apply_patch(
        SecuritySettingsOverrides(
            user_directory_admin_only=True,
            password_min_length=12,
            mask_credential_prefix=False,
        ),
        present_keys={
            "user_directory_admin_only",
            "password_min_length",
            "mask_credential_prefix",
        },
    )

    assert _load_row_as_dict() == {"user_directory_admin_only": True}
