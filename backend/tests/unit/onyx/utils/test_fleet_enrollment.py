"""The sender reads one stored key, enrolls with it, and never blocks startup."""

import hashlib
import threading
import time
import uuid
from typing import Any
from unittest.mock import Mock

import pytest

from onyx.utils import fleet_telemetry as fleet
from tests.utils.fleet_telemetry import (
    TEST_ENROLLMENT,
    TEST_KEY,
    RecordingTransport,
    Response,
    make_sender,
)


def test_sender_enrolls_once_with_the_stored_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key: Mock = Mock(return_value=TEST_KEY)
    monkeypatch.setattr(fleet, "deployment_key", key)
    sender: fleet.BoundedTelemetry = fleet.BoundedTelemetry("api")
    calls: list[tuple[str, dict[str, Any]]] = []
    record: RecordingTransport = RecordingTransport()

    def transport(url: str, **kwargs: Any) -> Response:
        calls.append((url, kwargs))
        return record(url, **kwargs)

    for _ in range(2):
        assert sender.emit("heartbeat", {"dropped_events": 0})
        assert sender.flush_once(transport)
    assert [url.rsplit("/", 1)[1] for url, _ in calls] == ["enroll", "events", "events"]
    assert {kwargs["headers"]["Authorization"] for _, kwargs in calls} == {
        "Bearer " + TEST_KEY
    }
    assert calls[0][1]["json"] == {"is_cloud": fleet.MULTI_TENANT}
    key.assert_called_once()
    # The service assigns the IDs that every event carries.
    assert {e["customer_uuid"] for e in record.events} == {
        TEST_ENROLLMENT["customer_uuid"]
    }
    assert {e["deployment_id"] for e in record.events} == {
        TEST_ENROLLMENT["deployment_id"]
    }


@pytest.mark.parametrize(
    "answer",
    [Response({}, status=503), Response({"customer_uuid": "not-a-uuid"})],
)
def test_failed_enrollment_keeps_events_and_backs_off(
    monkeypatch: pytest.MonkeyPatch, answer: Response
) -> None:
    monkeypatch.setattr(fleet, "deployment_key", Mock(return_value=TEST_KEY))
    sender: fleet.BoundedTelemetry = fleet.BoundedTelemetry("api")
    assert sender.emit("heartbeat", {"dropped_events": 0})
    transport: Mock = Mock(return_value=answer)
    assert not sender.flush_once(transport)
    assert len(sender._queue) == 1
    assert sender._blocked_until > time.monotonic()
    assert not sender.flush_once(transport)
    assert transport.call_count == 1


def test_unknown_key_enrolls_again() -> None:
    sender: fleet.BoundedTelemetry = make_sender()
    assert sender.emit("heartbeat", {"dropped_events": 0})
    assert not sender.flush_once(Mock(return_value=Response({}, status=401)))
    sender._blocked_until = 0.0
    record: RecordingTransport = RecordingTransport()
    calls: list[str] = []

    def transport(url: str, **kwargs: Any) -> Response:
        calls.append(url.rsplit("/", 1)[1])
        return record(url, **kwargs)

    assert sender.flush_once(transport)
    assert calls == ["enroll", "events"] and len(record.events) == 1


def test_startup_and_shutdown_never_wait_for_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered: threading.Event = threading.Event()
    release: threading.Event = threading.Event()

    def blocked_key() -> str:
        entered.set()
        release.wait(5)
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(fleet, "DISABLE_TELEMETRY", False)
    monkeypatch.setattr(fleet, "deployment_key", blocked_key)
    monkeypatch.setattr(fleet, "_client", None)
    started: float = time.monotonic()
    sender: fleet.BoundedTelemetry | None = fleet.start_telemetry("api")
    try:
        assert sender is not None
        assert time.monotonic() - started < 0.1
        assert entered.wait(2)
        # Events queue while the sender waits for the key.
        assert fleet.emit_telemetry("heartbeat", {"dropped_events": 0})
        assert fleet.start_telemetry("api") is sender
        stopped: float = time.monotonic()
        fleet.stop_telemetry()
        assert time.monotonic() - stopped < 0.1
    finally:
        release.set()
        if sender is not None:
            sender.close(2)


def test_cloud_key_comes_from_the_web_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fleet, "MULTI_TENANT", True)
    monkeypatch.setattr(fleet, "WEB_DOMAIN", "https://cloud.example")
    assert (
        fleet.deployment_key()
        == hashlib.sha256(b"onyx-cloud:https://cloud.example").hexdigest()
    )


def test_cloud_tenants_report_as_scoped_customers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fleet, "MULTI_TENANT", True)
    sender: fleet.BoundedTelemetry = make_sender()
    for tenant in ("tenant_a", "tenant_b"):
        assert sender.emit("heartbeat", {"dropped_events": 0}, tenant_id=tenant)
    assert sender.emit(
        "resource", {"memory_bytes": 100, "shared": True}, tenant_id="tenant_a"
    )
    first, second, shared = sender._take_batch()
    deployment: str = TEST_ENROLLMENT["customer_uuid"]
    assert first["customer_uuid"] != second["customer_uuid"]
    assert first["customer_uuid"] == str(
        uuid.uuid5(uuid.UUID(deployment), first["installation_scope"])
    )
    assert "tenant_a" not in str(first)
    assert shared["customer_uuid"] == deployment
    assert "installation_scope" not in shared
