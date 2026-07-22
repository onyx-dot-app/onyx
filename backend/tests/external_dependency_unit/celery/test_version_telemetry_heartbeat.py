"""Tests for the self-hosted version telemetry heartbeat task.

Verifies the daily dedupe behavior (Redis marker) and the multi-tenant no-op,
using a real Redis instance and a mocked telemetry sender.
"""

from collections.abc import Generator
from unittest.mock import patch

import pytest

from onyx import __version__
from onyx.background.celery.tasks.monitoring.tasks import (
    _VERSION_TELEMETRY_EMITTED_KEY,
    emit_version_telemetry,
)
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.telemetry import RecordType
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE

_TENANT_ID = POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE


@pytest.fixture
def clear_version_telemetry_marker() -> Generator[None, None, None]:
    redis_client = get_redis_client(tenant_id=_TENANT_ID)
    redis_client.delete(_VERSION_TELEMETRY_EMITTED_KEY)
    try:
        yield
    finally:
        redis_client.delete(_VERSION_TELEMETRY_EMITTED_KEY)


@pytest.mark.usefixtures("clear_version_telemetry_marker")
def test_emits_version_once_per_day() -> None:
    with patch(
        "onyx.background.celery.tasks.monitoring.tasks.optional_telemetry"
    ) as mock_telemetry:
        emit_version_telemetry(tenant_id=_TENANT_ID)

        mock_telemetry.assert_called_once_with(
            record_type=RecordType.VERSION,
            data={"version": __version__},
            tenant_id=_TENANT_ID,
        )

        # Marker is set, so subsequent runs within the TTL window are no-ops
        emit_version_telemetry(tenant_id=_TENANT_ID)
        emit_version_telemetry(tenant_id=_TENANT_ID)
        assert mock_telemetry.call_count == 1

    # Once the marker expires (simulated by deleting it), the task emits again
    redis_client = get_redis_client(tenant_id=_TENANT_ID)
    redis_client.delete(_VERSION_TELEMETRY_EMITTED_KEY)

    with patch(
        "onyx.background.celery.tasks.monitoring.tasks.optional_telemetry"
    ) as mock_telemetry:
        emit_version_telemetry(tenant_id=_TENANT_ID)
        assert mock_telemetry.call_count == 1


@pytest.mark.usefixtures("clear_version_telemetry_marker")
def test_marker_has_expiration() -> None:
    with patch("onyx.background.celery.tasks.monitoring.tasks.optional_telemetry"):
        emit_version_telemetry(tenant_id=_TENANT_ID)

    redis_client = get_redis_client(tenant_id=_TENANT_ID)
    ttl = redis_client.ttl(_VERSION_TELEMETRY_EMITTED_KEY)
    # A marker without a TTL (-1) would permanently silence the heartbeat
    assert 0 < ttl <= 24 * 60 * 60


@pytest.mark.usefixtures("clear_version_telemetry_marker")
def test_noop_on_multi_tenant() -> None:
    with (
        patch(
            "onyx.background.celery.tasks.monitoring.tasks.MULTI_TENANT",
            True,
        ),
        patch(
            "onyx.background.celery.tasks.monitoring.tasks.optional_telemetry"
        ) as mock_telemetry,
    ):
        emit_version_telemetry(tenant_id=_TENANT_ID)

    mock_telemetry.assert_not_called()
    redis_client = get_redis_client(tenant_id=_TENANT_ID)
    assert not redis_client.exists(_VERSION_TELEMETRY_EMITTED_KEY)


def test_task_is_scheduled_self_hosted() -> None:
    """The heartbeat must be present in the self-hosted beat schedule."""
    from onyx.background.celery.tasks.beat_schedule import get_tasks_to_schedule
    from onyx.configs.constants import OnyxCeleryTask

    scheduled_task_names = {entry["task"] for entry in get_tasks_to_schedule()}
    assert OnyxCeleryTask.EMIT_VERSION_TELEMETRY in scheduled_task_names
