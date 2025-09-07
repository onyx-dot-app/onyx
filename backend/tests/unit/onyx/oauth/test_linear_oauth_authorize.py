import json
from typing import Any

import pytest
from pytest_mock import MockerFixture

from onyx.configs.constants import DocumentSource


@pytest.fixture
def fake_kv_store(mocker: MockerFixture) -> Any:
    class FakeKV:
        def __init__(self) -> None:
            self._data: dict[str, Any] = {}

        def store(self, key: str, value: Any, encrypt: bool = False) -> None:
            self._data[key] = value

        def load(self, key: str) -> Any:
            if key not in self._data:
                from onyx.key_value_store.interface import KvKeyNotFoundError

                raise KvKeyNotFoundError(key)
            return self._data[key]

        def delete(self, key: str) -> None:
            self._data.pop(key, None)

    fake_kv = FakeKV()
    # Preload Linear app creds
    fake_kv.store(
        "linear_app_credential",
        json.dumps({"client_id": "CID123", "client_secret": "SECRET456"}),
    )
    # Patch the KV store used by Linear app credential helpers
    mocker.patch("onyx.connectors.linear.linear_kv.get_kv_store", return_value=fake_kv)
    return fake_kv


@pytest.fixture
def fake_redis(mocker: MockerFixture) -> Any:
    class FakeRedis:
        def __init__(self) -> None:
            self._data: dict[str, Any] = {}

        def set(self, key: str, value: str, ex: Any | None = None) -> None:
            self._data[key] = value

        def get(self, key: str) -> Any:
            return self._data.get(key)

    fake_redis = FakeRedis()
    mocker.patch(
        "onyx.server.documents.standard_oauth.get_redis_client", return_value=fake_redis
    )
    return fake_redis


@pytest.fixture
def fake_auth(mocker: MockerFixture) -> Any:
    from onyx.db.models import User

    fake_user = User(id=1, email="test@example.com", is_active=True, is_superuser=True)
    mocker.patch(
        "onyx.server.documents.standard_oauth.current_user", return_value=fake_user
    )
    return fake_user


def test_oauth_authorize_injection_logic(
    fake_kv_store: Any, fake_redis: Any, mocker: MockerFixture
) -> None:
    """Test the injection logic without using TestClient"""
    from onyx.server.documents.standard_oauth import oauth_authorize
    from fastapi import Request
    from onyx.db.models import User

    # Mock dependencies
    mock_request = mocker.Mock(spec=Request)
    mock_request.query_params = {}
    mock_user = User(id=1, email="test@example.com", is_active=True, is_superuser=True)

    # Mock the required functions
    mocker.patch(
        "onyx.server.documents.standard_oauth.current_user", return_value=mock_user
    )
    mocker.patch(
        "onyx.server.documents.standard_oauth.WEB_DOMAIN", "https://test.example.com"
    )
    mocker.patch(
        "onyx.server.documents.standard_oauth.get_current_tenant_id", return_value=None
    )

    # Mock KV store to avoid database calls
    mocker.patch(
        "onyx.connectors.linear.linear_kv.get_kv_store", return_value=fake_kv_store
    )

    # Mock connector discovery
    from onyx.connectors.linear.connector import LinearConnector

    mocker.patch(
        "onyx.server.documents.standard_oauth._discover_oauth_connectors",
        return_value={DocumentSource.LINEAR: LinearConnector},
    )

    # Mock additional_kwargs function to return empty dict initially
    mocker.patch(
        "onyx.server.documents.standard_oauth._get_additional_kwargs", return_value={}
    )

    # Mock Linear connector's authorization URL method
    mock_url = "https://linear.app/oauth/authorize?client_id=CID123&redirect_uri=https://test.example.com/oauth/callback&response_type=code&scope=read&state=test_state&prompt=consent"
    mocker.patch.object(
        LinearConnector, "oauth_authorization_url", return_value=mock_url
    )

    # Call the function
    response = oauth_authorize(mock_request, DocumentSource.LINEAR)

    # Verify the response
    assert response.url == mock_url
    assert "client_id=CID123" in response.url
    assert "linear.app/oauth/authorize" in response.url


def test_oauth_injection_handles_missing_credentials(
    fake_kv_store: Any, fake_redis: Any, mocker: MockerFixture
) -> None:
    """Test that injection logic handles missing credentials gracefully"""
    from onyx.server.documents.standard_oauth import oauth_authorize
    from fastapi import Request
    from onyx.db.models import User

    # Mock dependencies
    mock_request = mocker.Mock(spec=Request)
    mock_request.query_params = {}
    mock_user = User(id=1, email="test@example.com", is_active=True, is_superuser=True)

    # Mock the required functions
    mocker.patch(
        "onyx.server.documents.standard_oauth.current_user", return_value=mock_user
    )
    mocker.patch(
        "onyx.server.documents.standard_oauth.WEB_DOMAIN", "https://test.example.com"
    )
    mocker.patch(
        "onyx.server.documents.standard_oauth.get_current_tenant_id", return_value=None
    )

    # Mock KV store to avoid database calls
    mocker.patch(
        "onyx.connectors.linear.linear_kv.get_kv_store", return_value=fake_kv_store
    )

    # Mock connector discovery
    from onyx.connectors.linear.connector import LinearConnector

    mocker.patch(
        "onyx.server.documents.standard_oauth._discover_oauth_connectors",
        return_value={DocumentSource.LINEAR: LinearConnector},
    )

    # Mock additional_kwargs function to return empty dict initially
    mocker.patch(
        "onyx.server.documents.standard_oauth._get_additional_kwargs", return_value={}
    )

    # Mock KV store to not have credentials
    fake_kv_store._data.pop("linear_app_credential", None)

    # Mock Linear connector's authorization URL method to raise error when no client_id
    def mock_oauth_url(
        base_domain: str, state: str, additional_kwargs: dict[str, str]
    ) -> str:
        if not additional_kwargs.get("client_id"):
            raise ValueError("Linear client_id is not configured")
        return "https://linear.app/oauth/authorize?client_id=test"

    mocker.patch.object(
        LinearConnector, "oauth_authorization_url", side_effect=mock_oauth_url
    )

    # Call the function - should fail because no credentials are configured
    with pytest.raises(ValueError, match="Linear client_id is not configured"):
        oauth_authorize(mock_request, DocumentSource.LINEAR)


def test_oauth_state_storage_with_injected_credentials(
    fake_kv_store: Any, fake_redis: Any, mocker: MockerFixture
) -> None:
    """Test that injected credentials are properly stored in Redis state"""
    from onyx.server.documents.standard_oauth import oauth_authorize
    from fastapi import Request
    from onyx.db.models import User

    # Mock dependencies
    mock_request = mocker.Mock(spec=Request)
    mock_request.query_params = {}
    mock_user = User(id=1, email="test@example.com", is_active=True, is_superuser=True)

    # Mock the required functions
    mocker.patch(
        "onyx.server.documents.standard_oauth.current_user", return_value=mock_user
    )
    mocker.patch(
        "onyx.server.documents.standard_oauth.WEB_DOMAIN", "https://test.example.com"
    )
    mocker.patch(
        "onyx.server.documents.standard_oauth.get_current_tenant_id", return_value=None
    )

    # Mock KV store to avoid database calls
    mocker.patch(
        "onyx.connectors.linear.linear_kv.get_kv_store", return_value=fake_kv_store
    )

    # Mock connector discovery
    from onyx.connectors.linear.connector import LinearConnector

    mocker.patch(
        "onyx.server.documents.standard_oauth._discover_oauth_connectors",
        return_value={DocumentSource.LINEAR: LinearConnector},
    )

    # Mock additional_kwargs function to return empty dict initially
    mocker.patch(
        "onyx.server.documents.standard_oauth._get_additional_kwargs", return_value={}
    )

    # Mock Linear connector's authorization URL method
    mock_url = "https://linear.app/oauth/authorize?client_id=CID123"
    mocker.patch.object(
        LinearConnector, "oauth_authorization_url", return_value=mock_url
    )

    # Call the function
    oauth_authorize(mock_request, DocumentSource.LINEAR)

    # Verify that state was stored in Redis
    state_keys = [k for k in fake_redis._data.keys() if k.startswith("oauth_state:")]
    assert len(state_keys) == 1

    state_key = state_keys[0]
    state_data = json.loads(fake_redis._data[state_key])

    # Verify additional_kwargs contains injected client_id
    assert "additional_kwargs" in state_data
    additional_kwargs = state_data["additional_kwargs"]
    assert additional_kwargs["client_id"] == "CID123"
    assert (
        "client_secret" not in additional_kwargs
    )  # Secret should not be stored in state
