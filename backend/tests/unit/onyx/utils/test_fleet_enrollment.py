"""Enrollment runs off the application path and cannot change installation scope."""

import os
import threading
import time
from typing import Any
from unittest.mock import Mock

import pytest

from onyx.utils import fleet_telemetry as fleet
from tests.unit.onyx.utils.test_fleet_telemetry import Response


@pytest.mark.parametrize("explicit_url", [False, True])
def test_database_connections_apply_source_tls_only_to_standard_settings(
    monkeypatch: pytest.MonkeyPatch, explicit_url: bool
) -> None:
    from onyx.db import fleet_enrollment, fleet_telemetry
    from onyx.db.engine import pg_ssl

    monkeypatch.setattr(pg_ssl, "USE_IAM_AUTH", False)
    monkeypatch.setattr(pg_ssl, "POSTGRES_SSLMODE", "verify-full")
    monkeypatch.setattr(pg_ssl, "POSTGRES_SSLROOTCERT", "/test/ca.crt")
    monkeypatch.setattr(pg_ssl, "POSTGRES_SSLCERT", "/test/client.crt")
    monkeypatch.setattr(pg_ssl, "POSTGRES_SSLKEY", "/test/client.key")
    if explicit_url:
        monkeypatch.setenv("ONYX_TELEMETRY_DATABASE_URL", "postgresql://explicit")
    else:
        monkeypatch.delenv("ONYX_TELEMETRY_DATABASE_URL", raising=False)
    for module, operation in (
        (fleet_enrollment, fleet_enrollment.installation_seed),
        (
            fleet_telemetry,
            lambda: fleet_telemetry.collector_engine("postgresql://test"),
        ),
    ):
        factory: Mock = Mock(side_effect=RuntimeError("connection intercepted"))
        monkeypatch.setattr(module, "create_engine", factory)
        with pytest.raises(RuntimeError, match="connection intercepted"):
            operation()
        options: dict[str, Any] = factory.call_args.kwargs["connect_args"]
        assert options["connect_timeout"] == 2
        if module is fleet_enrollment or not explicit_url:
            assert options["sslmode"] == "verify-full"
            assert options["sslrootcert"] == "/test/ca.crt"
            assert options["sslcert"] == "/test/client.crt"
            assert options["sslkey"] == "/test/client.key"
        else:
            assert not any(key.startswith("ssl") for key in options)


def test_auto_identity_is_stable_and_privacy_key_stays_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DISABLE_TELEMETRY", raising=False)
    monkeypatch.delenv("ONYX_TELEMETRY_ENDPOINT", raising=False)
    first = fleet.automatic_config("api", b"a" * 32)
    second = fleet.automatic_config("collector", b"a" * 32)
    other = fleet.automatic_config("api", b"b" * 32)
    assert first and second and other
    assert first.endpoint == "https://telemetry.onyx.app"
    assert first.token == second.token and first.customer_uuid == second.customer_uuid
    assert first.customer_uuid != other.customer_uuid
    assert first.privacy_key.decode() != first.token
    sender = fleet.BoundedTelemetry(first)
    calls = []

    def transport(url: str, **kwargs: object) -> Response:
        calls.append((url, kwargs))
        if url.endswith("/enroll"):
            return Response(
                {
                    "customer_uuid": first.customer_uuid,
                    "deployment_id": first.deployment_id,
                }
            )
        return Response({"results": [{"index": 0, "status": "accepted"}]})

    sender.emit("heartbeat", {"dropped_events": 0})
    assert sender.flush_once(transport)
    sender.emit("heartbeat", {"dropped_events": 0})
    assert sender.flush_once(transport)
    assert [url.rsplit("/", 1)[1] for url, _ in calls] == ["enroll", "events", "events"]
    assert first.privacy_key.decode() not in str(calls)
    assert calls[0][1]["json"] == {"is_cloud": fleet.MULTI_TENANT}


def test_failed_or_mismatched_enrollment_retains_bounded_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DISABLE_TELEMETRY", raising=False)
    config = fleet.automatic_config("api", b"a" * 32)
    assert config
    sender = fleet.BoundedTelemetry(config)
    sender.emit("heartbeat", {"dropped_events": 0})
    transport = Mock(return_value=Response({"customer_uuid": "wrong"}))
    assert not sender.flush_once(transport)
    assert len(sender._pending) == 1
    assert not sender._enrolled
    assert sender._blocked_until > time.monotonic()
    assert not sender.flush_once(transport)
    assert transport.call_count == 1


def test_startup_and_shutdown_do_not_wait_for_identity_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.db import fleet_enrollment

    for key in tuple(os.environ):
        if key.startswith("ONYX_TELEMETRY_") or key == "DISABLE_TELEMETRY":
            monkeypatch.delenv(key)
    entered = threading.Event()
    release = threading.Event()

    def blocked_seed() -> bytes:
        entered.set()
        release.wait(5)
        return b"a" * 32

    monkeypatch.setattr(fleet_enrollment, "installation_seed", blocked_seed)
    monkeypatch.setattr(fleet, "_client", None)
    monkeypatch.setattr(fleet, "_bootstrap_thread", None)
    monkeypatch.setattr(fleet, "_bootstrap_stop", threading.Event())
    started = time.monotonic()
    try:
        assert fleet.start_telemetry() is None
        assert time.monotonic() - started < 0.1
        assert entered.wait(1)
        first_thread = fleet._bootstrap_thread
        assert fleet.start_telemetry() is None
        assert fleet._bootstrap_thread is first_thread
        stopped = time.monotonic()
        fleet.stop_telemetry()
        assert time.monotonic() - stopped < 0.1
    finally:
        release.set()
        if fleet._bootstrap_thread:
            fleet._bootstrap_thread.join(2)
    assert fleet._client is None


def test_partial_override_and_opt_out_do_not_enroll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fleet, "_client", None)
    start = Mock(side_effect=AssertionError("started background work"))
    monkeypatch.setattr(threading.Thread, "start", start)
    monkeypatch.setenv("DISABLE_TELEMETRY", "true")
    assert fleet.start_telemetry() is None
    monkeypatch.delenv("DISABLE_TELEMETRY")
    monkeypatch.setenv("ONYX_TELEMETRY_TOKEN", "partial")
    assert fleet.start_telemetry() is None
    start.assert_not_called()


def test_automatic_cloud_scopes_cannot_collide_with_explicit_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import uuid

    monkeypatch.delenv("DISABLE_TELEMETRY", raising=False)
    monkeypatch.setattr(fleet, "MULTI_TENANT", True)
    config = fleet.automatic_config("api", b"c" * 32)
    assert config
    sender = fleet.BoundedTelemetry(config)
    for tenant in ("tenant_a", "tenant_b"):
        assert sender.emit("heartbeat", {"dropped_events": 0}, tenant_id=tenant)
    assert sender.emit("resource", {"memory_bytes": 100, "shared": True})
    first, second, shared = sender._take_batch()
    assert first["customer_uuid"] != second["customer_uuid"]
    assert first["customer_uuid"] == str(
        uuid.uuid5(uuid.UUID(config.customer_uuid), first["installation_scope"])
    )
    assert "tenant_a" not in str(first)
    assert shared["customer_uuid"] == config.customer_uuid
    assert "installation_scope" not in shared
