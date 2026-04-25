import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch


def _make_app():
    from fastapi import FastAPI
    from knowledge_layer.server.query import router, require_user as query_require_user
    from knowledge_layer.providers.base import QueryResult
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[query_require_user] = lambda: MagicMock()
    return app


def test_query_endpoint_returns_answer():
    mock_topic = MagicMock()
    mock_topic.id = 1
    mock_topic.name = "trading"

    mock_page = MagicMock()
    mock_page.slug = "trading-signals"
    mock_page.title = "Trading Signals"
    mock_page.content = "Signals are indicators."

    with patch("knowledge_layer.server.query.get_session") as mock_session_ctx, \
         patch("knowledge_layer.server.query.ClaudeProvider") as mock_provider_cls:

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_topic
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_page]
        mock_session_ctx.return_value.__enter__ = lambda s: mock_db
        mock_session_ctx.return_value.__exit__ = MagicMock(return_value=False)

        from knowledge_layer.providers.base import QueryResult
        mock_provider = MagicMock()
        mock_provider.query_call.return_value = QueryResult(
            answer="Trading signals are market indicators.",
            citations=["trading-signals"]
        )
        mock_provider_cls.return_value = mock_provider

        app = _make_app()
        client = TestClient(app)
        resp = client.post("/topics/1/query", json={"question": "What are trading signals?"})

    assert resp.status_code == 200
    data = resp.json()
    assert "indicators" in data["answer"]
    assert "trading-signals" in data["citations"]


def test_query_endpoint_404_for_missing_topic():
    with patch("knowledge_layer.server.query.get_session") as mock_session_ctx:
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_session_ctx.return_value.__enter__ = lambda s: mock_db
        mock_session_ctx.return_value.__exit__ = MagicMock(return_value=False)

        app = _make_app()
        client = TestClient(app)
        resp = client.post("/topics/999/query", json={"question": "Anything?"})

    assert resp.status_code == 404
