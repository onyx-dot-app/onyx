"""`/health` backs the Helm liveness and readiness probes.

The app uses a throwaway Prometheus registry: the instrumentator registers on
the global one when the middleware stack is built, so sharing it with another
instrumented test raises on duplicate timeseries.
"""

from collections.abc import Generator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry
from prometheus_fastapi_instrumentator import Instrumentator

from onyx.webhook_server.api import create_webhook_app


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    isolated = Instrumentator(registry=CollectorRegistry())
    with patch(
        "onyx.webhook_server.api.create_prometheus_instrumentator",
        return_value=isolated,
    ):
        app = create_webhook_app()
    with TestClient(app) as test_client:
        yield test_client


def test_health_answers_without_auth(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "webhook_server"}


def test_health_tolerates_a_trailing_slash(client: TestClient) -> None:
    assert client.get("/health/").status_code == 200


def test_metrics_is_not_open(client: TestClient) -> None:
    """The ingress publishes this app's whole path, so /metrics stays shut.

    Pinned so the assertion reads the locked default, not the environment.
    """
    with patch("onyx.server.metrics.metrics_auth.DISABLE_METRICS_AUTH", False):
        assert client.get("/metrics").status_code == 401


def test_serves_no_event_route_yet(client: TestClient) -> None:
    """Guards the slice boundary: receipt routes land in a later change."""
    assert client.post("/connector/events/mock_connector").status_code == 404
