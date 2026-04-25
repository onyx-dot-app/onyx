import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock


def _make_app():
    from fastapi import FastAPI
    from unittest.mock import MagicMock
    from knowledge_layer.server.topics import router, require_user
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_user] = lambda: MagicMock()
    return app


def test_create_topic_returns_201():
    with patch("knowledge_layer.server.topics.get_session") as mock_session_ctx:
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_session_ctx.return_value.__enter__ = lambda s: mock_db
        mock_session_ctx.return_value.__exit__ = MagicMock(return_value=False)

        app = _make_app()
        client = TestClient(app)
        resp = client.post("/topics", json={
            "name": "trading",
            "description": "Trading knowledge base",
            "watch_path": "/raw/trading"
        })
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "trading"
    assert data["watch_path"] == "/raw/trading"


def test_create_topic_duplicate_name_returns_409():
    with patch("knowledge_layer.server.topics.get_session") as mock_session_ctx:
        existing = MagicMock()
        existing.name = "trading"
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = existing
        mock_session_ctx.return_value.__enter__ = lambda s: mock_db
        mock_session_ctx.return_value.__exit__ = MagicMock(return_value=False)

        app = _make_app()
        client = TestClient(app)
        resp = client.post("/topics", json={
            "name": "trading",
            "description": "Duplicate",
            "watch_path": "/raw/trading"
        })
    assert resp.status_code == 409


def test_create_topic_rejects_path_traversal():
    """watch_path outside TEAM_BRAIN_RAW_ROOT returns 422."""
    import os
    with patch("knowledge_layer.server.topics.get_session") as mock_session_ctx, \
         patch.dict(os.environ, {"TEAM_BRAIN_RAW_ROOT": "/raw"}):
        # Force re-evaluation of the module-level _RAW_ROOT
        import knowledge_layer.server.topics as topics_module
        from pathlib import Path
        topics_module._RAW_ROOT = Path("/raw").resolve()

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_session_ctx.return_value.__enter__ = lambda s: mock_db
        mock_session_ctx.return_value.__exit__ = MagicMock(return_value=False)

        app = _make_app()
        client = TestClient(app)
        resp = client.post("/topics", json={
            "name": "evil",
            "description": "attacker",
            "watch_path": "../../etc"
        })
    assert resp.status_code == 422


def test_list_topics_returns_200():
    with patch("knowledge_layer.server.topics.get_session") as mock_session_ctx:
        mock_db = MagicMock()
        mock_db.query.return_value.all.return_value = []
        mock_session_ctx.return_value.__enter__ = lambda s: mock_db
        mock_session_ctx.return_value.__exit__ = MagicMock(return_value=False)

        app = _make_app()
        client = TestClient(app)
        resp = client.get("/topics")
    assert resp.status_code == 200
    assert resp.json() == []


def test_delete_topic_returns_204():
    with patch("knowledge_layer.server.topics.get_session") as mock_session_ctx:
        existing = MagicMock()
        existing.id = 1
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = existing
        mock_session_ctx.return_value.__enter__ = lambda s: mock_db
        mock_session_ctx.return_value.__exit__ = MagicMock(return_value=False)

        app = _make_app()
        client = TestClient(app)
        resp = client.delete("/topics/1")

    assert resp.status_code == 204
    mock_db.delete.assert_called_once_with(existing)
    mock_db.commit.assert_called()


def test_delete_topic_404_for_missing():
    with patch("knowledge_layer.server.topics.get_session") as mock_session_ctx:
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_session_ctx.return_value.__enter__ = lambda s: mock_db
        mock_session_ctx.return_value.__exit__ = MagicMock(return_value=False)

        app = _make_app()
        client = TestClient(app)
        resp = client.delete("/topics/999")

    assert resp.status_code == 404
