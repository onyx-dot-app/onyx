"""Tests for the daily deployment snapshot telemetry task."""

from collections.abc import Generator
from unittest.mock import patch

import pytest

from onyx.background.celery.tasks.monitoring.tasks import (
    _DEPLOYMENT_SNAPSHOT_EMITTED_KEY,
    emit_deployment_snapshot_telemetry,
)
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.telemetry import RecordType
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE

_TENANT_ID = POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE


@pytest.fixture(autouse=True)
def enable_telemetry() -> Generator[None, None, None]:
    # CI runs with DISABLE_TELEMETRY=true; force the task's gate open so the
    # snapshot logic under test actually executes
    with patch(
        "onyx.background.celery.tasks.monitoring.tasks.DISABLE_TELEMETRY",
        False,
    ):
        yield


@pytest.fixture
def clear_snapshot_marker() -> Generator[None, None, None]:
    redis_client = get_redis_client(tenant_id=_TENANT_ID)
    redis_client.delete(_DEPLOYMENT_SNAPSHOT_EMITTED_KEY)
    try:
        yield
    finally:
        redis_client.delete(_DEPLOYMENT_SNAPSHOT_EMITTED_KEY)


@pytest.mark.usefixtures("clear_snapshot_marker")
def test_emits_snapshot_once_per_day() -> None:
    with patch(
        "onyx.background.celery.tasks.monitoring.tasks.optional_telemetry"
    ) as mock_telemetry:
        emit_deployment_snapshot_telemetry(tenant_id=_TENANT_ID)

        assert mock_telemetry.call_count == 1
        kwargs = mock_telemetry.call_args.kwargs
        assert kwargs["record_type"] == RecordType.DEPLOYMENT_SNAPSHOT
        assert kwargs["tenant_id"] == _TENANT_ID
        assert kwargs["blocking"] is True
        # sections the POC report is built from
        assert set(kwargs["data"]) == {
            "snapshot_at",
            "users",
            "connectors",
            "queries",
            "feedback",
        }

        emit_deployment_snapshot_telemetry(tenant_id=_TENANT_ID)
        emit_deployment_snapshot_telemetry(tenant_id=_TENANT_ID)
        assert mock_telemetry.call_count == 1


@pytest.mark.usefixtures("clear_snapshot_marker")
def test_failed_delivery_releases_marker() -> None:
    with patch(
        "onyx.background.celery.tasks.monitoring.tasks.optional_telemetry"
    ) as mock_telemetry:
        mock_telemetry.return_value = False
        emit_deployment_snapshot_telemetry(tenant_id=_TENANT_ID)

        redis_client = get_redis_client(tenant_id=_TENANT_ID)
        assert not redis_client.exists(_DEPLOYMENT_SNAPSHOT_EMITTED_KEY)

        # next tick retries; a successful send keeps the marker
        mock_telemetry.return_value = True
        emit_deployment_snapshot_telemetry(tenant_id=_TENANT_ID)
        assert mock_telemetry.call_count == 2
        assert redis_client.exists(_DEPLOYMENT_SNAPSHOT_EMITTED_KEY)


@pytest.mark.usefixtures("clear_snapshot_marker")
def test_snapshot_failure_releases_marker() -> None:
    """A snapshot that blows up must not silence the rest of the day."""
    with (
        patch(
            "onyx.background.celery.tasks.monitoring.tasks.build_deployment_snapshot",
            side_effect=RuntimeError("boom"),
        ),
        patch(
            "onyx.background.celery.tasks.monitoring.tasks.optional_telemetry"
        ) as mock_telemetry,
    ):
        emit_deployment_snapshot_telemetry(tenant_id=_TENANT_ID)

    mock_telemetry.assert_not_called()
    redis_client = get_redis_client(tenant_id=_TENANT_ID)
    assert not redis_client.exists(_DEPLOYMENT_SNAPSHOT_EMITTED_KEY)


@pytest.mark.usefixtures("clear_snapshot_marker")
def test_marker_has_expiration() -> None:
    with patch("onyx.background.celery.tasks.monitoring.tasks.optional_telemetry"):
        emit_deployment_snapshot_telemetry(tenant_id=_TENANT_ID)

    redis_client = get_redis_client(tenant_id=_TENANT_ID)
    # a marker without a TTL would permanently silence the report
    ttl = redis_client.ttl(_DEPLOYMENT_SNAPSHOT_EMITTED_KEY)
    assert 0 < ttl <= 24 * 60 * 60


@pytest.mark.usefixtures("clear_snapshot_marker")
def test_noop_when_telemetry_disabled() -> None:
    with (
        patch(
            "onyx.background.celery.tasks.monitoring.tasks.DISABLE_TELEMETRY",
            True,
        ),
        patch(
            "onyx.background.celery.tasks.monitoring.tasks.optional_telemetry"
        ) as mock_telemetry,
    ):
        emit_deployment_snapshot_telemetry(tenant_id=_TENANT_ID)

    mock_telemetry.assert_not_called()


def test_task_is_scheduled_for_self_hosted_and_cloud() -> None:
    from onyx.background.celery.tasks.beat_schedule import (
        beat_task_templates,
        get_tasks_to_schedule,
    )
    from onyx.configs.constants import OnyxCeleryTask

    task_name = OnyxCeleryTask.EMIT_DEPLOYMENT_SNAPSHOT_TELEMETRY
    assert task_name in {entry["task"] for entry in get_tasks_to_schedule()}
    # membership in the templates is what fans the task out per cloud tenant
    assert task_name in {entry["task"] for entry in beat_task_templates}
