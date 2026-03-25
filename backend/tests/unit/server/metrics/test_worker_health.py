"""Tests for WorkerHeartbeatMonitor and WorkerHealthCollector."""

import time
from unittest.mock import MagicMock

from onyx.server.metrics.indexing_pipeline import WorkerHealthCollector
from onyx.server.metrics.indexing_pipeline import WorkerHeartbeatMonitor


class TestWorkerHeartbeatMonitor:
    def test_heartbeat_registers_worker(self) -> None:
        monitor = WorkerHeartbeatMonitor(MagicMock())
        monitor._on_heartbeat({"hostname": "primary@host1"})

        status = monitor.get_worker_status()
        assert "primary" in status
        assert status["primary"] is True

    def test_multiple_workers(self) -> None:
        monitor = WorkerHeartbeatMonitor(MagicMock())
        monitor._on_heartbeat({"hostname": "primary@host1"})
        monitor._on_heartbeat({"hostname": "docfetching@host1"})
        monitor._on_heartbeat({"hostname": "monitoring@host1"})

        status = monitor.get_worker_status()
        assert len(status) == 3
        assert all(alive for alive in status.values())

    def test_offline_removes_worker(self) -> None:
        monitor = WorkerHeartbeatMonitor(MagicMock())
        monitor._on_heartbeat({"hostname": "primary@host1"})
        monitor._on_offline({"hostname": "primary@host1"})

        status = monitor.get_worker_status()
        assert "primary" not in status

    def test_stale_heartbeat_marks_worker_down(self) -> None:
        monitor = WorkerHeartbeatMonitor(MagicMock())
        # Inject a stale timestamp directly
        with monitor._lock:
            monitor._worker_last_seen["primary@host1"] = (
                time.monotonic() - monitor._HEARTBEAT_TIMEOUT_SECONDS - 10
            )

        status = monitor.get_worker_status()
        assert status["primary"] is False

    def test_heartbeat_refreshes_stale_worker(self) -> None:
        monitor = WorkerHeartbeatMonitor(MagicMock())
        # Start with stale
        with monitor._lock:
            monitor._worker_last_seen["primary@host1"] = (
                time.monotonic() - monitor._HEARTBEAT_TIMEOUT_SECONDS - 10
            )
        assert monitor.get_worker_status()["primary"] is False

        # Fresh heartbeat
        monitor._on_heartbeat({"hostname": "primary@host1"})
        assert monitor.get_worker_status()["primary"] is True

    def test_ignores_empty_hostname(self) -> None:
        monitor = WorkerHeartbeatMonitor(MagicMock())
        monitor._on_heartbeat({})
        monitor._on_heartbeat({"hostname": ""})
        monitor._on_offline({})

        assert monitor.get_worker_status() == {}

    def test_strips_hostname_suffix(self) -> None:
        monitor = WorkerHeartbeatMonitor(MagicMock())
        monitor._on_heartbeat({"hostname": "docprocessing@my-long-host.local"})

        status = monitor.get_worker_status()
        assert "docprocessing" in status
        assert "docprocessing@my-long-host.local" not in status

    def test_thread_safety(self) -> None:
        """get_worker_status should not raise even if heartbeats arrive concurrently."""
        monitor = WorkerHeartbeatMonitor(MagicMock())
        # Simulate concurrent access — just verify no deadlock/error
        monitor._on_heartbeat({"hostname": "primary@host1"})
        status = monitor.get_worker_status()
        monitor._on_heartbeat({"hostname": "primary@host1"})
        status2 = monitor.get_worker_status()
        assert status == status2


class TestWorkerHealthCollector:
    def test_returns_empty_when_no_monitor(self) -> None:
        collector = WorkerHealthCollector(cache_ttl=0)
        assert collector.collect() == []

    def test_collects_active_workers(self) -> None:
        monitor = WorkerHeartbeatMonitor(MagicMock())
        monitor._on_heartbeat({"hostname": "primary@host1"})
        monitor._on_heartbeat({"hostname": "docfetching@host1"})
        monitor._on_heartbeat({"hostname": "monitoring@host1"})

        collector = WorkerHealthCollector(cache_ttl=0)
        collector.set_monitor(monitor)

        families = collector.collect()
        assert len(families) == 2

        active = families[0]
        assert active.name == "onyx_celery_active_worker_count"
        assert active.samples[0].value == 3

        up = families[1]
        assert up.name == "onyx_celery_worker_up"
        assert len(up.samples) == 3
        for sample in up.samples:
            assert sample.value == 1

    def test_reports_dead_worker(self) -> None:
        monitor = WorkerHeartbeatMonitor(MagicMock())
        monitor._on_heartbeat({"hostname": "primary@host1"})
        # Make monitoring stale
        with monitor._lock:
            monitor._worker_last_seen["monitoring@host1"] = (
                time.monotonic() - monitor._HEARTBEAT_TIMEOUT_SECONDS - 10
            )

        collector = WorkerHealthCollector(cache_ttl=0)
        collector.set_monitor(monitor)

        families = collector.collect()
        active = families[0]
        assert active.samples[0].value == 1  # only primary is alive

        up = families[1]
        samples_by_name = {s.labels["worker"]: s.value for s in up.samples}
        assert samples_by_name["primary"] == 1
        assert samples_by_name["monitoring"] == 0

    def test_empty_monitor_returns_zero(self) -> None:
        monitor = WorkerHeartbeatMonitor(MagicMock())

        collector = WorkerHealthCollector(cache_ttl=0)
        collector.set_monitor(monitor)

        families = collector.collect()
        active = families[0]
        assert active.samples[0].value == 0
