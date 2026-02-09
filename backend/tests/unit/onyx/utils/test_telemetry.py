from typing import Any
from unittest.mock import Mock

from onyx.configs.constants import MilestoneRecordType
from onyx.utils import telemetry as telemetry_utils


def test_mt_cloud_telemetry_noop_when_not_multi_tenant(monkeypatch: Any) -> None:
    fetch_impl = Mock()
    monkeypatch.setattr(
        telemetry_utils,
        "fetch_versioned_implementation_with_fallback",
        fetch_impl,
    )
    # mt_cloud_telemetry reads the module-local imported symbol, so patch this path.
    monkeypatch.setattr("onyx.utils.telemetry.MULTI_TENANT", False)

    telemetry_utils.mt_cloud_telemetry(
        tenant_id="tenant-1",
        distinct_id="user@example.com",
        event=MilestoneRecordType.USER_MESSAGE_SENT,
        properties={"origin": "web"},
    )

    fetch_impl.assert_not_called()


def test_mt_cloud_telemetry_calls_event_telemetry_when_multi_tenant(
    monkeypatch: Any,
) -> None:
    event_telemetry = Mock()
    fetch_impl = Mock(return_value=event_telemetry)
    monkeypatch.setattr(
        telemetry_utils,
        "fetch_versioned_implementation_with_fallback",
        fetch_impl,
    )
    # mt_cloud_telemetry reads the module-local imported symbol, so patch this path.
    monkeypatch.setattr("onyx.utils.telemetry.MULTI_TENANT", True)

    telemetry_utils.mt_cloud_telemetry(
        tenant_id="tenant-1",
        distinct_id="user@example.com",
        event=MilestoneRecordType.USER_MESSAGE_SENT,
        properties={"origin": "web"},
    )

    fetch_impl.assert_called_once_with(
        module="onyx.utils.telemetry",
        attribute="event_telemetry",
        fallback=telemetry_utils.noop_fallback,
    )
    event_telemetry.assert_called_once_with(
        "user@example.com",
        MilestoneRecordType.USER_MESSAGE_SENT,
        {"origin": "web", "tenant_id": "tenant-1"},
    )
