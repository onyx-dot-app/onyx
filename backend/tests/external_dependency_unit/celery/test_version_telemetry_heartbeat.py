"""Tests for the self-hosted version telemetry heartbeat task."""

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


@pytest.fixture(autouse=True)
def enable_telemetry() -> Generator[None, None, None]:
    # CI runs with DISABLE_TELEMETRY=true; force the task's gate open so the
    # heartbeat logic under test actually executes
    with patch(
        "onyx.background.celery.tasks.monitoring.tasks.DISABLE_TELEMETRY",
        False,
    ):
        yield


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
            blocking=True,
        )

        emit_version_telemetry(tenant_id=_TENANT_ID)
        emit_version_telemetry(tenant_id=_TENANT_ID)
        assert mock_telemetry.call_count == 1

    # marker expiry (simulated by deleting it) allows the next report
    redis_client = get_redis_client(tenant_id=_TENANT_ID)
    redis_client.delete(_VERSION_TELEMETRY_EMITTED_KEY)

    with patch(
        "onyx.background.celery.tasks.monitoring.tasks.optional_telemetry"
    ) as mock_telemetry:
        emit_version_telemetry(tenant_id=_TENANT_ID)
        assert mock_telemetry.call_count == 1


@pytest.mark.usefixtures("clear_version_telemetry_marker")
def test_failed_delivery_releases_marker() -> None:
    with patch(
        "onyx.background.celery.tasks.monitoring.tasks.optional_telemetry"
    ) as mock_telemetry:
        mock_telemetry.return_value = False
        emit_version_telemetry(tenant_id=_TENANT_ID)

        redis_client = get_redis_client(tenant_id=_TENANT_ID)
        assert not redis_client.exists(_VERSION_TELEMETRY_EMITTED_KEY)

        # next tick retries; a successful send keeps the marker
        mock_telemetry.return_value = True
        emit_version_telemetry(tenant_id=_TENANT_ID)
        assert mock_telemetry.call_count == 2
        assert redis_client.exists(_VERSION_TELEMETRY_EMITTED_KEY)


@pytest.mark.usefixtures("clear_version_telemetry_marker")
def test_marker_has_expiration() -> None:
    with patch("onyx.background.celery.tasks.monitoring.tasks.optional_telemetry"):
        emit_version_telemetry(tenant_id=_TENANT_ID)

    redis_client = get_redis_client(tenant_id=_TENANT_ID)
    # a marker without a TTL would permanently silence the heartbeat
    ttl = redis_client.ttl(_VERSION_TELEMETRY_EMITTED_KEY)
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
    from onyx.background.celery.tasks.beat_schedule import get_tasks_to_schedule
    from onyx.configs.constants import OnyxCeleryTask

    scheduled_task_names = {entry["task"] for entry in get_tasks_to_schedule()}
    assert OnyxCeleryTask.EMIT_VERSION_TELEMETRY in scheduled_task_names
