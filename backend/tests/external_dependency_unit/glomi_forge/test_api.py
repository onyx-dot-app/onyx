import uuid
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_create_session_returns_id(monkeypatch):
    from onyx.db.enums import GlomiForgeStatus
    from onyx.glomi_forge.schemas.forge_spec import ForgeSpec
    from onyx.server.features.glomi_forge import api as mod

    session_id = uuid.uuid4()
    created_sessions: list[tuple[str, object]] = []
    enqueued: list[tuple[uuid.UUID, str]] = []

    def fake_create_session(_db_session, **kwargs):
        created_sessions.append((kwargs["title"], kwargs["artifact_type"]))
        return SimpleNamespace(id=session_id, status=GlomiForgeStatus.QUEUED)

    def fake_build_spec(request, _artifact_type):
        return ForgeSpec(title="测试页", goal=request)

    monkeypatch.setattr(mod, "ENABLE_GLOMI_FORGE", True)
    monkeypatch.setattr(mod, "_build_spec", fake_build_spec)
    monkeypatch.setattr(mod, "create_glomi_forge_session", fake_create_session)
    monkeypatch.setattr(
        mod,
        "enqueue_forge_session",
        lambda sid, tenant_id: enqueued.append((sid, tenant_id)),
    )
    monkeypatch.setattr(mod, "get_current_tenant_id", lambda: "tenant-a")
    app = FastAPI()
    app.dependency_overrides[mod.current_user] = lambda: None
    app.dependency_overrides[mod.get_session] = lambda: object()
    app.include_router(mod.router)

    client = TestClient(app)
    response = client.post(
        "/glomi-forge/sessions",
        json={"request": "做个落地页", "artifact_type": "landing_page"},
    )

    assert response.status_code == 200
    assert response.json() == {"session_id": str(session_id), "status": "queued"}
    assert created_sessions == [("测试页", mod.ForgeArtifactType.LANDING_PAGE)]
    assert enqueued == [(session_id, "tenant-a")]
