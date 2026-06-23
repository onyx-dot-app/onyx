"""Tests for the impersonation feature gate.

Exercises the gate through the actual endpoint (in-process via TestClient) so we
verify both the gate logic *and* that the dependency is wired to the route. The
cloud-superuser auth dependency is overridden so we test the feature flag in
isolation, and the flag itself is toggled via monkeypatch (works because the
endpoint runs in this same process).
"""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi_users import exceptions

from ee.onyx.auth.users import current_cloud_superuser
from ee.onyx.server.tenants import admin_api
from onyx.error_handling.exceptions import register_onyx_exception_handlers


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(admin_api.router)
    register_onyx_exception_handlers(app)
    # Bypass the cloud-superuser auth gate; we're testing the feature flag here.
    app.dependency_overrides[current_cloud_superuser] = lambda: None
    return TestClient(app)


def test_returns_403_env_var_gated_when_disabled(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(admin_api, "IMPERSONATION_ENABLED", False)

    resp = client.post("/tenants/impersonate", json={"email": "user@example.com"})

    assert resp.status_code == 403
    assert resp.json()["error_code"] == "ENV_VAR_GATED"


def test_passes_gate_when_enabled(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(admin_api, "IMPERSONATION_ENABLED", True)

    # Stop in the handler body right after the gate so we don't touch the DB;
    # reaching this code proves the request got past the feature gate.
    with patch.object(
        admin_api,
        "get_tenant_id_for_email",
        side_effect=exceptions.UserNotExists,
    ):
        resp = client.post("/tenants/impersonate", json={"email": "user@example.com"})

    assert resp.status_code == 422
    assert resp.json().get("error_code") != "ENV_VAR_GATED"
