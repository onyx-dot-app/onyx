"""Tests for SCIM exception handlers.

These tests use FastAPI's TestClient to exercise the full request lifecycle,
ensuring that HTTPExceptions (e.g. auth failures), validation errors, and
unhandled exceptions are converted to SCIM-formatted error responses for
``/scim/v2/*`` paths while preserving default FastAPI behavior elsewhere.
"""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from fastapi import APIRouter
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient

from ee.onyx.server.scim.api import _get_provider
from ee.onyx.server.scim.api import scim_router
from ee.onyx.server.scim.auth import verify_scim_token
from ee.onyx.server.scim.error_handlers import register_scim_error_handlers
from ee.onyx.server.scim.models import SCIM_ERROR_SCHEMA
from onyx.db.engine.sql_engine import get_session


def _mock_session() -> Generator[MagicMock, None, None]:
    yield MagicMock()


def _deny_auth() -> None:
    """Dependency override that always rejects with 401."""
    raise HTTPException(status_code=401, detail="Invalid SCIM bearer token")


def _allow_auth() -> MagicMock:
    """Dependency override that always allows auth."""
    token = MagicMock()
    token.id = 1
    return token


def _build_test_app() -> FastAPI:
    """Build a minimal FastAPI app with SCIM and a non-SCIM route.

    Overrides ``get_session`` so the test app doesn't need a real database.
    """
    app = FastAPI()
    app.include_router(scim_router)

    # Override get_session so dependency resolution doesn't require a DB engine
    app.dependency_overrides[get_session] = _mock_session

    # A non-SCIM route to verify default behavior is preserved
    other = APIRouter()

    @other.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @other.get("/api/error")
    def error() -> None:
        raise HTTPException(status_code=403, detail="forbidden")

    app.include_router(other)
    register_scim_error_handlers(app)
    return app


@pytest.fixture
def app() -> FastAPI:
    return _build_test_app()


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


class TestScimAuthErrors:
    """Auth failures should return SCIM error format for /scim/v2/ paths."""

    def test_missing_token_returns_scim_error(self, client: TestClient) -> None:
        """GET /scim/v2/Users without token → 401 in SCIM format."""
        response = client.get("/scim/v2/Users")
        assert response.status_code == 401
        body = response.json()
        assert SCIM_ERROR_SCHEMA in body.get("schemas", [])
        assert body["status"] == "401"
        assert "detail" in body

    def test_invalid_token_returns_scim_error(
        self, app: FastAPI, client: TestClient
    ) -> None:
        """GET /scim/v2/Users with bad token → 401 in SCIM format."""
        app.dependency_overrides[verify_scim_token] = _deny_auth
        response = client.get(
            "/scim/v2/Users",
            headers={"Authorization": "Bearer onyx_scim_bad_token"},
        )
        assert response.status_code == 401
        body = response.json()
        assert SCIM_ERROR_SCHEMA in body.get("schemas", [])
        assert body["status"] == "401"

    def test_content_type_is_scim_json(self, client: TestClient) -> None:
        """SCIM error responses use application/scim+json content type."""
        response = client.get("/scim/v2/Users")
        assert "application/scim+json" in response.headers.get("content-type", "")


class TestScimValidationErrors:
    """Pydantic validation failures should return SCIM 400 for /scim/v2/ paths."""

    def test_missing_required_field_returns_400(
        self, app: FastAPI, client: TestClient
    ) -> None:
        """POST /scim/v2/Users with empty body → 400 in SCIM format."""
        app.dependency_overrides[verify_scim_token] = _allow_auth
        app.dependency_overrides[_get_provider] = MagicMock

        response = client.post(
            "/scim/v2/Users",
            json={},
            headers={"Authorization": "Bearer onyx_scim_test"},
        )

        assert response.status_code == 400
        body = response.json()
        assert SCIM_ERROR_SCHEMA in body.get("schemas", [])
        assert body["status"] == "400"
        assert "userName" in body.get("detail", "").lower() or "detail" in body

    def test_invalid_json_returns_400(self, client: TestClient) -> None:
        """POST /scim/v2/Users with malformed JSON → 400 in SCIM format."""
        response = client.post(
            "/scim/v2/Users",
            content=b"not-json",
            headers={
                "Authorization": "Bearer onyx_scim_test",
                "Content-Type": "application/json",
            },
        )

        # FastAPI may return 400 or 422 for malformed JSON — either way,
        # the response should be SCIM-formatted for SCIM paths
        assert response.status_code in (400, 422)
        body = response.json()
        assert SCIM_ERROR_SCHEMA in body.get("schemas", [])


class TestNonScimRoutesPreserved:
    """Non-SCIM routes should use FastAPI's default error format."""

    def test_non_scim_http_exception_uses_default_format(
        self, client: TestClient
    ) -> None:
        """GET /api/error → default FastAPI error format (not SCIM)."""
        response = client.get("/api/error")
        assert response.status_code == 403
        body = response.json()
        # Default FastAPI format: {"detail": "forbidden"}
        assert body == {"detail": "forbidden"}
        assert "schemas" not in body

    def test_non_scim_route_works_normally(self, client: TestClient) -> None:
        """GET /api/health → normal response."""
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"ok": True}


class TestScimServiceDiscovery:
    """Service discovery endpoints should work without auth."""

    def test_service_provider_config(self, client: TestClient) -> None:
        response = client.get("/scim/v2/ServiceProviderConfig")
        assert response.status_code == 200

    def test_resource_types(self, client: TestClient) -> None:
        response = client.get("/scim/v2/ResourceTypes")
        assert response.status_code == 200

    def test_schemas(self, client: TestClient) -> None:
        response = client.get("/scim/v2/Schemas")
        assert response.status_code == 200


class TestUnhandledExceptions:
    """Unhandled exceptions in SCIM routes should return SCIM 500."""

    def test_unhandled_exception_returns_scim_500(
        self, app: FastAPI, client: TestClient
    ) -> None:
        """Simulate an unhandled exception in a SCIM endpoint."""
        app.dependency_overrides[verify_scim_token] = _allow_auth

        with patch(
            "ee.onyx.server.scim.api.parse_scim_filter",
            side_effect=RuntimeError("unexpected"),
        ):
            response = client.get(
                "/scim/v2/Users",
                headers={"Authorization": "Bearer onyx_scim_test"},
            )

        assert response.status_code == 500
        body = response.json()
        assert SCIM_ERROR_SCHEMA in body.get("schemas", [])
        assert body["status"] == "500"
        assert body["detail"] == "Internal server error"
        assert "application/scim+json" in response.headers.get("content-type", "")
