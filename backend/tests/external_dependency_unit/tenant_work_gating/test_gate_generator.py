"""Tests for `cloud_beat_task_generator`'s tenant work-gating logic.

Exercises the gate-read path end-to-end against real Redis. The Celery
`.app.send_task` is mocked so we can count dispatches without actually
sending messages.

Requires a running Redis instance. Run with::

    python -m dotenv -f .vscode/.env run -- pytest \
        backend/tests/external_dependency_unit/tenant_work_gating/test_gate_generator.py
"""

from collections.abc import Generator
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from ee.onyx.background.celery.tasks.cloud import tasks as cloud_tasks
from onyx.configs.constants import ONYX_CLOUD_TENANT_ID
from onyx.redis import redis_tenant_work_gating as twg
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.redis_tenant_work_gating import _SET_KEY
from onyx.redis.redis_tenant_work_gating import mark_tenant_active

_TENANT_A = "tenant_aaaa0000-0000-0000-0000-000000000001"
_TENANT_B = "tenant_bbbb0000-0000-0000-0000-000000000002"
_TENANT_C = "tenant_cccc0000-0000-0000-0000-000000000003"
_ALL_TEST_TENANTS = [_TENANT_A, _TENANT_B, _TENANT_C]
_FANOUT_KEY_PREFIX = cloud_tasks._FULL_FANOUT_TIMESTAMP_KEY_PREFIX


@pytest.fixture(autouse=True)
def _multi_tenant_true() -> Generator[None, None, None]:
    with patch.object(twg, "MULTI_TENANT", True):
        yield


@pytest.fixture(autouse=True)
def _clean_redis() -> Generator[None, None, None]:
    """Clear the active set AND the per-task full-fanout timestamp so each
    test starts fresh."""
    r = get_redis_client(tenant_id=ONYX_CLOUD_TENANT_ID)
    r.delete(_SET_KEY)
    r.delete(f"{_FANOUT_KEY_PREFIX}:test_task")
    r.delete("runtime:tenant_work_gating:enabled")
    r.delete("runtime:tenant_work_gating:enforce")
    yield
    r.delete(_SET_KEY)
    r.delete(f"{_FANOUT_KEY_PREFIX}:test_task")
    r.delete("runtime:tenant_work_gating:enabled")
    r.delete("runtime:tenant_work_gating:enforce")


def _invoke_generator(
    *,
    work_gated: bool,
    enabled: bool,
    enforce: bool,
    tenant_ids: list[str],
    full_fanout_interval_seconds: int = 1200,
    ttl_seconds: int = 1800,
) -> MagicMock:
    """Helper: call the generator with runtime flags fixed and the Celery
    app mocked. Returns the mock so callers can assert on send_task calls."""
    mock_app = MagicMock()
    # The task binds `self` = the task itself when invoked via `.run()`;
    # patch its `.app` so `self.app.send_task` routes to our mock.
    with (
        patch.object(cloud_tasks.cloud_beat_task_generator, "app", mock_app),
        patch.object(cloud_tasks, "get_all_tenant_ids", return_value=list(tenant_ids)),
        patch.object(cloud_tasks, "get_gated_tenants", return_value=set()),
        patch(
            "onyx.server.runtime.onyx_runtime.OnyxRuntime.get_tenant_work_gating_enabled",
            return_value=enabled,
        ),
        patch(
            "onyx.server.runtime.onyx_runtime.OnyxRuntime.get_tenant_work_gating_enforce",
            return_value=enforce,
        ),
        patch(
            "onyx.server.runtime.onyx_runtime.OnyxRuntime.get_tenant_work_gating_full_fanout_interval_seconds",
            return_value=full_fanout_interval_seconds,
        ),
        patch(
            "onyx.server.runtime.onyx_runtime.OnyxRuntime.get_tenant_work_gating_ttl_seconds",
            return_value=ttl_seconds,
        ),
    ):
        cloud_tasks.cloud_beat_task_generator.run(
            task_name="test_task",
            work_gated=work_gated,
        )
    return mock_app


def _dispatched_tenants(mock_app: MagicMock) -> list[str]:
    """Pull tenant_ids out of each send_task call for assertion."""
    return [c.kwargs["kwargs"]["tenant_id"] for c in mock_app.send_task.call_args_list]


def _seed_recent_full_fanout_timestamp() -> None:
    """Pre-seed the per-task timestamp so the interval-elapsed branch
    reports False, i.e. the gate enforces normally instead of going into
    full-fanout on first invocation."""
    import time as _t

    r = get_redis_client(tenant_id=ONYX_CLOUD_TENANT_ID)
    r.set(f"{_FANOUT_KEY_PREFIX}:test_task", str(int(_t.time() * 1000)))


def test_enforce_skips_unmarked_tenants() -> None:
    """With enable+enforce on (interval NOT elapsed), only tenants in the
    active set get dispatched."""
    mark_tenant_active(_TENANT_A)
    _seed_recent_full_fanout_timestamp()

    mock_app = _invoke_generator(
        work_gated=True,
        enabled=True,
        enforce=True,
        tenant_ids=_ALL_TEST_TENANTS,
        full_fanout_interval_seconds=3600,
    )

    dispatched = _dispatched_tenants(mock_app)
    assert dispatched == [_TENANT_A]


def test_shadow_mode_dispatches_all_tenants() -> None:
    """enabled=True, enforce=False: gate computes skip but still dispatches."""
    mark_tenant_active(_TENANT_A)
    _seed_recent_full_fanout_timestamp()

    mock_app = _invoke_generator(
        work_gated=True,
        enabled=True,
        enforce=False,
        tenant_ids=_ALL_TEST_TENANTS,
        full_fanout_interval_seconds=3600,
    )

    dispatched = _dispatched_tenants(mock_app)
    assert set(dispatched) == set(_ALL_TEST_TENANTS)


def test_full_fanout_cycle_dispatches_all_tenants() -> None:
    """First invocation (no prior timestamp → interval considered elapsed)
    counts as full-fanout; every tenant gets dispatched even under enforce."""
    mark_tenant_active(_TENANT_A)

    mock_app = _invoke_generator(
        work_gated=True,
        enabled=True,
        enforce=True,
        tenant_ids=_ALL_TEST_TENANTS,
    )

    dispatched = _dispatched_tenants(mock_app)
    assert set(dispatched) == set(_ALL_TEST_TENANTS)


def test_redis_unavailable_fails_open() -> None:
    """When `get_active_tenants` returns None (simulated Redis outage) the
    gate treats the invocation as full-fanout and dispatches everyone —
    even when the interval hasn't elapsed and enforce is on."""
    mark_tenant_active(_TENANT_A)
    _seed_recent_full_fanout_timestamp()

    with patch.object(cloud_tasks, "get_active_tenants", return_value=None):
        mock_app = _invoke_generator(
            work_gated=True,
            enabled=True,
            enforce=True,
            tenant_ids=_ALL_TEST_TENANTS,
            full_fanout_interval_seconds=3600,
        )

    dispatched = _dispatched_tenants(mock_app)
    assert set(dispatched) == set(_ALL_TEST_TENANTS)


def test_work_gated_false_bypasses_gate_entirely() -> None:
    """Beat templates that don't opt in (`work_gated=False`) never consult
    the set — no matter the flag state."""
    # Even with enforce on and nothing in the set, all tenants dispatch.
    mock_app = _invoke_generator(
        work_gated=False,
        enabled=True,
        enforce=True,
        tenant_ids=_ALL_TEST_TENANTS,
    )

    dispatched = _dispatched_tenants(mock_app)
    assert set(dispatched) == set(_ALL_TEST_TENANTS)


def test_gate_disabled_dispatches_everyone_regardless_of_enforce() -> None:
    """enabled=False means the gate isn't computed — dispatch is unchanged."""
    # Intentionally don't add anyone to the set.
    mock_app = _invoke_generator(
        work_gated=True,
        enabled=False,
        enforce=True,
        tenant_ids=_ALL_TEST_TENANTS,
    )

    dispatched = _dispatched_tenants(mock_app)
    assert set(dispatched) == set(_ALL_TEST_TENANTS)
