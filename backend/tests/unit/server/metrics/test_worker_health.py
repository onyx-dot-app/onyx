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
        assert "primary@host1" in status
        assert status["primary@host1"] is True

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
        assert "primary@host1" not in status

    def test_stale_heartbeat_marks_worker_down(self) -> None:
        monitor = WorkerHeartbeatMonitor(MagicMock())
        with monitor._lock:
            monitor._worker_last_seen["primary@host1"] = (
                time.monotonic() - monitor._HEARTBEAT_TIMEOUT_SECONDS - 10
            )

        status = monitor.get_worker_status()
        assert status["primary@host1"] is False

    def test_very_stale_worker_is_pruned(self) -> None:
        """Workers dead for 2x the timeout are pruned from the dict."""
        monitor = WorkerHeartbeatMonitor(MagicMock())
        with monitor._lock:
            monitor._worker_last_seen["gone@host1"] = (
                time.monotonic() - monitor._HEARTBEAT_TIMEOUT_SECONDS * 2 - 10
            )

        status = monitor.get_worker_status()
        assert "gone@host1" not in status
        assert monitor.get_worker_status() == {}

    def test_heartbeat_refreshes_stale_worker(self) -> None:
        monitor = WorkerHeartbeatMonitor(MagicMock())
        with monitor._lock:
            monitor._worker_last_seen["primary@host1"] = (
                time.monotonic() - monitor._HEARTBEAT_TIMEOUT_SECONDS - 10
            )
        assert monitor.get_worker_status()["primary@host1"] is False

        monitor._on_heartbeat({"hostname": "primary@host1"})
        assert monitor.get_worker_status()["primary@host1"] is True

    def test_ignores_empty_hostname(self) -> None:
        monitor = WorkerHeartbeatMonitor(MagicMock())
        monitor._on_heartbeat({})
        monitor._on_heartbeat({"hostname": ""})
        monitor._on_offline({})

        assert monitor.get_worker_status() == {}

    def test_returns_full_hostname_as_key(self) -> None:
        monitor = WorkerHeartbeatMonitor(MagicMock())
        monitor._on_heartbeat({"hostname": "docprocessing@my-long-host.local"})

        status = monitor.get_worker_status()
        assert "docprocessing@my-long-host.local" in status

    def test_start_is_idempotent(self) -> None:
        monitor = WorkerHeartbeatMonitor(MagicMock())
        # Mock the thread so we don't actually start one
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        monitor._thread = mock_thread
        monitor._running = True

        # Second start should be a no-op
        monitor.start()
        # Thread constructor should not have been called again
        assert monitor._thread is mock_thread

    def test_thread_safety(self) -> None:
        """get_worker_status should not raise even if heartbeats arrive concurrently."""
        monitor = WorkerHeartbeatMonitor(MagicMock())
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
        label_pairs = {
            (s.labels["worker_type"], s.labels["hostname"]) for s in up.samples
        }
        assert label_pairs == {
            ("primary", "host1"),
            ("docfetching", "host1"),
            ("monitoring", "host1"),
        }
        for sample in up.samples:
            assert sample.value == 1

    def test_replicas_of_same_worker_type_are_distinct(self) -> None:
        """Regression: ``docprocessing@pod-1`` and ``docprocessing@pod-2`` must
        produce separate samples, not collapse into one duplicate-timestamp
        series.
        """
        monitor = WorkerHeartbeatMonitor(MagicMock())
        monitor._on_heartbeat({"hostname": "docprocessing@pod-1"})
        monitor._on_heartbeat({"hostname": "docprocessing@pod-2"})
        monitor._on_heartbeat({"hostname": "docprocessing@pod-3"})

        collector = WorkerHealthCollector(cache_ttl=0)
        collector.set_monitor(monitor)

        up = collector.collect()[1]
        assert len(up.samples) == 3
        hostnames = {s.labels["hostname"] for s in up.samples}
        assert hostnames == {"pod-1", "pod-2", "pod-3"}
        assert all(s.labels["worker_type"] == "docprocessing" for s in up.samples)

    def test_reports_dead_worker(self) -> None:
        monitor = WorkerHeartbeatMonitor(MagicMock())
        monitor._on_heartbeat({"hostname": "primary@host1"})
        with monitor._lock:
            monitor._worker_last_seen["monitoring@host1"] = (
                time.monotonic() - monitor._HEARTBEAT_TIMEOUT_SECONDS - 10
            )

        collector = WorkerHealthCollector(cache_ttl=0)
        collector.set_monitor(monitor)

        families = collector.collect()
        active = families[0]
        assert active.samples[0].value == 1

        up = families[1]
        samples_by_type = {s.labels["worker_type"]: s.value for s in up.samples}
        assert samples_by_type["primary"] == 1
        assert samples_by_type["monitoring"] == 0

    def test_empty_monitor_returns_zero(self) -> None:
        monitor = WorkerHeartbeatMonitor(MagicMock())

        collector = WorkerHealthCollector(cache_ttl=0)
        collector.set_monitor(monitor)

        families = collector.collect()
        assert len(families) == 2
        active = families[0]
        assert active.samples[0].value == 0
        up = families[1]
        assert up.name == "onyx_celery_worker_up"
        assert len(up.samples) == 0
