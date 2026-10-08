"""Kubernetes health reads export opaque identities and bounded, fixed values."""

import gzip
import io
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest

from onyx.utils import fleet_telemetry as fleet
from onyx.utils import fleet_telemetry_kubernetes as kubernetes
from onyx.utils.fleet_telemetry_kubernetes import KubernetesCollector, quantity
from tests.utils.fleet_telemetry import Response, make_sender


@pytest.mark.parametrize("status", [410, 500])
def test_kubernetes_expired_page_recovers_but_transient_failure_keeps_cursor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, status: int
) -> None:
    clock: list[float] = [100.0]
    monkeypatch.setattr(kubernetes, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    sender: fleet.BoundedTelemetry = make_sender()
    watcher: KubernetesCollector = KubernetesCollector(sender)
    watcher.token_path = tmp_path / "token"
    watcher.token_path.write_text("test-token")
    pages: list[dict[str, Any]] = []

    def get(path: str, **kwargs: Any) -> Response:
        if "/apis/metrics" in path:
            return Response({"items": []})
        pages.append(dict(kwargs["params"]))
        if len(pages) == 1:
            return Response({"items": [], "metadata": {"continue": "page-two"}})
        if len(pages) == 2:
            return Response({}, status=status)
        return Response({"items": [], "metadata": {}})

    monkeypatch.setattr("requests.get", get)
    watcher.tick()
    clock[0] += 30
    watcher.tick()
    watcher.tick()
    assert len(pages) == 2  # Keep the bounded cadence after a rejected page.
    clock[0] += 30
    watcher.tick()
    assert pages == [
        {"limit": 25},
        {"limit": 25, "continue": "page-two"},
        {"limit": 25} if status == 410 else {"limit": 25, "continue": "page-two"},
    ]
    assert watcher.errors == 1


def test_kubernetes_events_have_opaque_ids_actual_limits_and_no_names() -> None:
    sender = make_sender()
    watcher = KubernetesCollector(sender)
    pods = {
        "items": [
            {
                "metadata": {
                    "uid": "private-pod-id",
                    "name": "private-pod",
                    "labels": {"app": "api-server", "customer": "private"},
                },
                "spec": {
                    "containers": [
                        {
                            "name": "private-container",
                            "resources": {"limits": {"memory": "1Gi", "cpu": "500m"}},
                        }
                    ]
                },
                "status": {
                    "containerStatuses": [
                        {
                            "name": "private-container",
                            "restartCount": 2,
                            "ready": False,
                            "state": {
                                "terminated": {
                                    "reason": "OOMKilled",
                                    "exitCode": 137,
                                    "message": "password=private",
                                }
                            },
                        }
                    ]
                },
            }
        ]
    }
    watcher.observe_pods(pods)
    watcher.observe_metrics(
        {
            "items": [
                {
                    "metadata": {"name": "private-pod"},
                    "containers": [
                        {
                            "name": "private-container",
                            "usage": {"memory": "512Mi", "cpu": "250m"},
                        }
                    ],
                }
            ]
        }
    )
    events = sender._take_batch()
    assert "private" not in json.dumps(events)
    assert events[0]["data"]["reason"] == "oom"
    assert events[0]["service"] == "api"
    assert events[0]["data"]["shared"] is True
    assert events[1]["data"]["memory_limit_bytes"] == 1024**3
    assert events[1]["data"]["cpu_limit_cores"] == 0.5
    assert quantity("max", cpu=True) is None


def test_kubernetes_large_environment_never_enters_telemetry() -> None:
    sender = make_sender()
    watcher = KubernetesCollector(sender)
    pod = {
        "metadata": {
            "name": "PRIVATE",
            "uid": "opaque-uid",
            "labels": {"app": "api-server"},
        },
        "spec": {
            "containers": [
                {
                    "name": "PRIVATE",
                    "env": [{"name": "SECRET", "value": "PRIVATE" * 8000}],
                    "resources": {},
                }
            ]
        },
        "status": {
            "containerStatuses": [{"name": "PRIVATE", "restartCount": 0, "ready": True}]
        },
    }
    watcher.observe_pods({"items": [pod]})
    assert len(sender._queue) == 1
    assert "PRIVATE" not in json.dumps(sender._take_batch())


def test_kubernetes_cloud_service_roles_are_fixed_and_other_labels_ignored() -> None:
    sender = make_sender()
    watcher = KubernetesCollector(sender)
    known = {
        "web-server": "web",
        "celery-worker-scheduled-tasks": "worker",
        "pgbouncer": "postgres",
        "mcp-server": "api",
        "telemetry-collector-canary": "collector",
    }
    pods = [
        {
            "metadata": {
                "name": "PRIVATE",
                "uid": str(index),
                "labels": {"app": name, "customer": "PRIVATE"},
            },
            "spec": {"containers": []},
            "status": {
                "containerStatuses": [
                    {"name": "PRIVATE", "restartCount": 0, "ready": True}
                ]
            },
        }
        for index, (name, _) in enumerate(known.items())
    ]
    watcher.observe_pods({"items": pods})
    events = sender._take_batch()
    assert [event["service"] for event in events] == list(known.values())
    assert "PRIVATE" not in json.dumps(events)


def test_kubernetes_initial_ready_history_is_not_a_fresh_failure() -> None:
    sender = make_sender()
    watcher = KubernetesCollector(sender)
    status = {
        "name": "PRIVATE",
        "restartCount": 9,
        "ready": True,
        "state": {"running": {}},
        "lastState": {"terminated": {"reason": "OOMKilled", "exitCode": 137}},
    }
    pod = {
        "metadata": {
            "name": "PRIVATE",
            "uid": "opaque",
            "labels": {"app": "api-server"},
        },
        "spec": {"containers": []},
        "status": {"containerStatuses": [status]},
    }
    watcher.observe_pods({"items": [pod]})
    initial = sender._take_batch()[0]["data"]
    assert (
        initial["reason"] == "started"
        and initial["restart_count"] == 9
        and initial["restart_delta"] == 0
    )
    assert "exit_code" not in initial
    watcher.observe_pods({"items": [pod]})
    assert not sender._queue
    status["restartCount"] = 12
    watcher.observe_pods({"items": [pod]})
    increased = sender._take_batch()[0]["data"]
    assert increased["reason"] == "oom" and increased["restart_delta"] == 3
    assert increased["shared"] is True
    watcher.observe_pods({"items": [pod]})
    assert not sender._queue
    status["ready"] = False
    status["state"] = {"waiting": {"reason": "PRIVATE"}}
    watcher.observe_pods({"items": [pod]})
    assert sender._take_batch()[0]["data"]["reason"] == "unready"
    status["state"] = {"terminated": {"reason": "OOMKilled", "exitCode": 137}}
    watcher.observe_pods({"items": [pod]})
    assert sender._take_batch()[0]["data"]["reason"] == "oom"


def test_kubernetes_version_reports_only_safe_tag_digest_once_and_on_change() -> None:
    sender = make_sender()
    watcher = KubernetesCollector(sender)
    container = {"name": "PRIVATE", "image": "PRIVATE.registry/PRIVATE:v1.2.3"}
    status = {
        "name": "PRIVATE",
        "imageID": "docker-pullable://PRIVATE/PRIVATE@sha256:" + "a" * 64,
        "restartCount": 0,
        "ready": True,
    }
    pod = {
        "metadata": {
            "name": "PRIVATE",
            "uid": "opaque-uid",
            "labels": {"app": "api-server"},
        },
        "spec": {"containers": [container]},
        "status": {"containerStatuses": [status]},
    }
    watcher.observe_pods({"items": [pod]})
    events = sender._take_batch()
    versions = [event for event in events if event["event_type"] == "version"]
    assert versions[0]["data"] == {
        "version": "v1.2.3",
        "image_digest": "sha256:" + "a" * 64,
        "shared": True,
    }
    assert versions[0]["service"] == "api"
    assert "PRIVATE" not in json.dumps(events)
    watcher.observe_pods({"items": [pod]})
    assert not sender._queue
    container["image"] = "PRIVATE.registry/PRIVATE:PRIVATE-customer-tag"
    watcher.observe_pods({"items": [pod]})
    assert sender._take_batch()[0]["data"]["version"] == "unknown"
    container["image"] = "PRIVATE.registry/PRIVATE:v1.2.4"
    watcher.observe_pods({"items": [pod]})
    assert sender._take_batch()[0]["data"]["version"] == "v1.2.4"


def test_kubernetes_ipv6_service_host_forms_a_valid_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "fd00:10:96::1")
    monkeypatch.setenv("KUBERNETES_SERVICE_PORT_HTTPS", "443")
    monkeypatch.delenv("ONYX_TELEMETRY_KUBERNETES_API_URL", raising=False)
    watcher = KubernetesCollector(make_sender())
    assert watcher.base == "https://[fd00:10:96::1]:443"
    assert urlsplit(watcher.base).port == 443


def test_memory_quantities_are_whole_bytes() -> None:
    assert quantity("1.1Ki") == 1126 and type(quantity("1.1Ki")) is int
    assert quantity("250m", cpu=True) == pytest.approx(0.25)


def test_unexpected_compression_fails_closed_with_bounded_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sender = make_sender()
    watcher = KubernetesCollector(sender)
    watcher.token_path = tmp_path / "token"
    watcher.token_path.write_text("test-token")

    def compressed(*_args: Any, **_kwargs: Any) -> Response:
        # A valid pod page and delivery receipt, rejected only for its encoding.
        response = Response(
            {"items": [], "results": [{"index": 0, "status": "accepted"}]}
        )
        response.headers["Content-Encoding"] = "gzip"
        response.raw = io.BytesIO(gzip.compress(response.raw.read()))
        return response

    monkeypatch.setattr("requests.get", compressed)
    assert watcher._get("/api/v1/namespaces/default/pods") is None
    assert watcher.errors == 1 and sender.health["kubernetes_errors"] == 1
    sender.emit("heartbeat", {"dropped_events": 0})
    assert not sender.flush_once(compressed)
    assert sender.failures == 1 and len(sender._pending) == 1
    assert sender.sent == 0


@pytest.mark.parametrize("uptime", [0.0, 1.0])
def test_initial_kubernetes_reads_run_once_and_failed_reads_keep_cadence(
    monkeypatch: pytest.MonkeyPatch, uptime: float
) -> None:
    clock = [uptime]
    monkeypatch.setattr(kubernetes, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    watcher = KubernetesCollector(make_sender())
    failed = Mock(return_value=None)
    monkeypatch.setattr(watcher, "_get", failed)
    watcher.tick()
    assert failed.call_count == 2
    assert failed.call_args_list[0].args[1] == {"limit": 25}
    watcher.tick()
    assert failed.call_count == 2
    clock[0] += 30
    watcher.tick()
    assert failed.call_count == 3
    clock[0] += 270
    watcher.tick()
    assert failed.call_count == 5
