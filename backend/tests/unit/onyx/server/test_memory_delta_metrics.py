"""Unit tests for per-endpoint memory delta middleware."""

from unittest.mock import MagicMock
from unittest.mock import patch

from fastapi import FastAPI
from starlette.testclient import TestClient

from onyx.server.metrics.memory_delta import _build_route_map
from onyx.server.metrics.memory_delta import _match_route
from onyx.server.metrics.memory_delta import add_memory_delta_middleware


def _make_app() -> FastAPI:
    app = FastAPI()

    @app.get("/api/chat/{chat_id}")
    def get_chat(chat_id: str) -> dict[str, str]:
        return {"id": chat_id}

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def test_build_route_map_extracts_api_routes() -> None:
    app = _make_app()
    route_map = _build_route_map(app)
    templates = [template for _, template in route_map]
    assert "/api/chat/{chat_id}" in templates
    assert "/api/health" in templates


def test_match_route_returns_template() -> None:
    app = _make_app()
    route_map = _build_route_map(app)
    assert _match_route(route_map, "/api/chat/abc-123") == "/api/chat/{chat_id}"
    assert _match_route(route_map, "/api/health") == "/api/health"
    assert _match_route(route_map, "/nonexistent") is None


@patch("onyx.server.metrics.memory_delta._process")
@patch("onyx.server.metrics.memory_delta._RSS_DELTA")
@patch("onyx.server.metrics.memory_delta._PROCESS_RSS")
def test_middleware_observes_rss_delta(
    mock_rss_gauge: MagicMock,
    mock_histogram: MagicMock,
    mock_process: MagicMock,
) -> None:
    """Verify the middleware measures RSS before/after and records the delta."""
    mem_before = MagicMock()
    mem_before.rss = 100_000_000
    mem_after = MagicMock()
    mem_after.rss = 100_065_536

    mock_process.memory_info.side_effect = [mem_before, mem_after]

    app = _make_app()
    add_memory_delta_middleware(app)

    client = TestClient(app)
    response = client.get("/api/health")

    assert response.status_code == 200
    mock_histogram.labels.assert_called_with(handler="/api/health")
    mock_histogram.labels().observe.assert_called_once_with(65_536)
    mock_rss_gauge.set.assert_called_once_with(100_065_536)


@patch("onyx.server.metrics.memory_delta._process")
@patch("onyx.server.metrics.memory_delta._RSS_DELTA")
@patch("onyx.server.metrics.memory_delta._PROCESS_RSS")
def test_middleware_uses_unmatched_for_unknown_paths(
    mock_rss_gauge: MagicMock,  # noqa: ARG001
    mock_histogram: MagicMock,
    mock_process: MagicMock,
) -> None:
    mem_info = MagicMock()
    mem_info.rss = 50_000_000
    mock_process.memory_info.return_value = mem_info

    app = _make_app()
    add_memory_delta_middleware(app)

    client = TestClient(app, raise_server_exceptions=False)
    client.get("/totally-unknown")

    mock_histogram.labels.assert_called_with(handler="unmatched")
