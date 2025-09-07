"""
Dynamic integration test for Linear UI-configurable OAuth flow.

This test validates the complete end-to-end flow:
1. Configure Linear app credentials via UI (management API)
2. Initiate OAuth authorization
3. Verify credentials are properly injected
4. Complete OAuth callback
5. Verify credential creation

This ensures the entire Linear connector UI configuration feature works as expected.
"""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from typing import Tuple

import pytest
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture

from onyx.configs.constants import DocumentSource


@pytest.fixture
def client(mocker: MockerFixture) -> Tuple[TestClient, dict[str, Any]]:
    """Test client with mocked dependencies"""
    # Import here to avoid issues with conftest
    from onyx.main import get_application

    # Mock all dependencies
    mock_db_session = mocker.Mock()
    mock_redis = mocker.Mock()
    mock_kv_store = mocker.Mock()
    mock_user = mocker.Mock()
    mock_user.id = 1
    mock_user.email = "admin@example.com"
    mock_user.is_active = True
    mock_user.is_superuser = True

    # Setup mocks
    mocker.patch(
        "onyx.server.documents.connector.get_session", return_value=mock_db_session
    )
    mocker.patch(
        "onyx.server.documents.standard_oauth.get_redis_client", return_value=mock_redis
    )
    mocker.patch(
        "onyx.server.documents.connector.get_redis_client", return_value=mock_redis
    )
    mocker.patch(
        "onyx.server.documents.standard_oauth.get_current_tenant_id", return_value=None
    )
    mocker.patch(
        "onyx.server.documents.standard_oauth.WEB_DOMAIN", "https://test.onyx.com"
    )
    mocker.patch(
        "onyx.server.documents.connector.current_curator_or_admin_user",
        return_value=mock_user,
    )
    mocker.patch(
        "onyx.server.documents.connector.current_admin_user", return_value=mock_user
    )
    mocker.patch(
        "onyx.server.documents.standard_oauth.current_user", return_value=mock_user
    )
    mocker.patch(
        "onyx.server.documents.standard_oauth.current_curator_or_admin_user",
        return_value=mock_user,
    )
    mocker.patch(
        "onyx.connectors.linear.linear_kv.get_kv_store", return_value=mock_kv_store
    )

    # Create app with minimal dependencies
    @asynccontextmanager
    async def _lifespan(_: Any) -> AsyncGenerator[None, None]:
        yield

    app = get_application(lifespan_override=_lifespan)

    return TestClient(app), {
        "db_session": mock_db_session,
        "redis": mock_redis,
        "kv_store": mock_kv_store,
        "user": mock_user,
    }


def test_linear_app_credential_management_flow(
    client: Tuple[TestClient, dict[str, Any]],
) -> None:
    """Test the complete Linear app credential management flow via API"""
    client_app, mocks = client

    # Mock KV store for initial empty state
    mocks["kv_store"].load.side_effect = ValueError(
        "Linear app credential is not configured"
    )

    # Step 1: Check initial state (no credentials configured) -> 404
    response = client_app.get("/api/manage/admin/connector/linear/app-credential")
    assert response.status_code == 404

    # Step 2: Configure Linear app credentials
    credentials = {"client_id": "test_client_123", "client_secret": "test_secret_456"}

    # Mock successful KV store operations
    mocks["kv_store"].store.return_value = None
    mocks["kv_store"].load.return_value = json.dumps(credentials)

    response = client_app.put(
        "/api/manage/admin/connector/linear/app-credential", json=credentials
    )
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert "Successfully saved Linear App Credentials" in response.json()["message"]

    # Step 3: Verify credentials are now configured
    response = client_app.get("/api/manage/admin/connector/linear/app-credential")
    assert response.status_code == 200
    data = response.json()
    assert data["client_id"] == "test_client_123"

    # Step 4: Delete credentials
    mocks["kv_store"].delete.return_value = None
    mocks["kv_store"].load.side_effect = ValueError(
        "Linear app credential is not configured"
    )

    response = client_app.delete("/api/manage/admin/connector/linear/app-credential")
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert "Successfully deleted Linear App Credentials" in response.json()["message"]

    # Step 5: Verify credentials are deleted -> 404
    response = client_app.get("/api/manage/admin/connector/linear/app-credential")
    assert response.status_code == 404


def test_linear_oauth_authorization_flow_with_credentials(
    client: Tuple[TestClient, dict[str, Any]], mocker: MockerFixture
) -> None:
    """Test OAuth authorization flow when Linear credentials are configured"""
    client_app, mocks = client

    # Mock connector discovery
    mock_connector_cls = mocker.Mock()
    mock_connector_cls.oauth_authorization_url.return_value = (
        "https://linear.app/oauth/authorize?client_id=test_client_123&"
        "redirect_uri=https://test.onyx.com/oauth/callback&response_type=code&"
        "scope=read&state=mock_state&prompt=consent"
    )

    mocker.patch(
        "onyx.server.documents.standard_oauth._discover_oauth_connectors",
        return_value={DocumentSource.LINEAR: mock_connector_cls},
    )

    # Configure credentials in KV store
    credentials = {"client_id": "test_client_123", "client_secret": "test_secret_456"}
    mocks["kv_store"].load.return_value = json.dumps(credentials)

    # Test OAuth authorization
    response = client_app.get("/api/connector/oauth/authorize/linear")
    assert response.status_code == 200

    data = response.json()
    assert "url" in data
    redirect_url = data["url"]

    # Verify that the redirect URL contains the injected client_id
    assert "client_id=test_client_123" in redirect_url
    assert "linear.app/oauth/authorize" in redirect_url
    assert "redirect_uri=" in redirect_url
    assert "scope=read" in redirect_url

    # Verify that connector's oauth_authorization_url was called with injected credentials
    mock_connector_cls.oauth_authorization_url.assert_called_once()
    call_args = mock_connector_cls.oauth_authorization_url.call_args[0]
    assert (
        call_args[2]["client_id"] == "test_client_123"
    )  # additional_kwargs should contain client_id
    assert "client_secret" in call_args[2]  # client_secret should be injected too


def test_linear_oauth_authorization_flow_without_credentials(
    client: Tuple[TestClient, dict[str, Any]], mocker: MockerFixture
) -> None:
    """Test OAuth authorization flow fails gracefully when Linear credentials are not configured"""
    client_app, mocks = client

    # Mock KV store to raise ValueError (no credentials)
    mocks["kv_store"].load.side_effect = ValueError(
        "Linear app credential is not configured"
    )

    # Mock connector discovery
    mock_connector_cls = mocker.Mock()
    mocker.patch(
        "onyx.server.documents.standard_oauth._discover_oauth_connectors",
        return_value={DocumentSource.LINEAR: mock_connector_cls},
    )

    # Test OAuth authorization without credentials - should still work but use env vars
    response = client_app.get("/api/connector/oauth/authorize/linear")

    # Should succeed (connector handles missing KV credentials by falling back to env vars)
    assert response.status_code == 200
    data = response.json()
    assert "url" in data

    # Verify connector was called
    mock_connector_cls.oauth_authorization_url.assert_called_once()


def test_linear_ui_oauth_end_to_end_flow(
    client: Tuple[TestClient, dict[str, Any]], mocker: MockerFixture
) -> None:
    """Test the complete end-to-end flow from UI configuration to OAuth completion"""
    client_app, mocks = client

    # Step 1: Configure credentials via UI
    credentials = {"client_id": "e2e_client_999", "client_secret": "e2e_secret_888"}

    mocks["kv_store"].store.return_value = None
    mocks["kv_store"].load.return_value = json.dumps(credentials)

    response = client_app.put(
        "/api/manage/admin/connector/linear/app-credential", json=credentials
    )
    assert response.status_code == 200

    # Step 2: Mock OAuth authorization
    mock_connector_cls = mocker.Mock()
    mock_connector_cls.oauth_authorization_url.return_value = (
        "https://linear.app/oauth/authorize?client_id=e2e_client_999&"
        "redirect_uri=https://test.onyx.com/oauth/callback&response_type=code&"
        "scope=read&state=e2e_state&prompt=consent"
    )

    mocker.patch(
        "onyx.server.documents.standard_oauth._discover_oauth_connectors",
        return_value={DocumentSource.LINEAR: mock_connector_cls},
    )

    response = client_app.get("/api/connector/oauth/authorize/linear")
    assert response.status_code == 200
    assert "e2e_client_999" in response.json()["url"]

    # Step 3: Simulate OAuth callback
    mock_connector_cls.oauth_code_to_token.return_value = {
        "linear_access_token": "e2e_access_token"
    }

    mocks["redis"].get.return_value = json.dumps(
        {
            "desired_return_url": "https://test.onyx.com/admin/connectors/linear?step=0",
            "additional_kwargs": {"client_id": "e2e_client_999"},
        }
    ).encode("utf-8")

    mock_create_credential = mocker.Mock()
    mock_create_credential.return_value = mocker.Mock(id=123)
    mocker.patch(
        "onyx.server.documents.standard_oauth.create_credential", mock_create_credential
    )

    response = client_app.get(
        "/api/connector/oauth/callback/linear",
        params={"code": "e2e_auth_code", "state": "e2e_state"},
    )
    assert response.status_code == 200

    # Step 4: Verify the complete flow worked
    mock_create_credential.assert_called_once()
    call_args = mock_create_credential.call_args[0][0]  # First positional argument
    assert call_args.source == DocumentSource.LINEAR
    assert call_args.credential_json["linear_access_token"] == "e2e_access_token"

    print("✅ End-to-end Linear UI OAuth flow completed successfully!")
