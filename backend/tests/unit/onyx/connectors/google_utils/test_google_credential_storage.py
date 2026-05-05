from typing import Any

import pytest

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import KV_GOOGLE_DRIVE_CRED_KEY
from onyx.configs.constants import KV_GOOGLE_DRIVE_SERVICE_ACCOUNT_KEY
from onyx.connectors.google_utils.google_kv import get_auth_url
from onyx.connectors.google_utils.google_kv import get_google_app_cred
from onyx.connectors.google_utils.google_kv import get_service_account_key
from onyx.connectors.google_utils.google_kv import upsert_google_app_cred
from onyx.connectors.google_utils.google_kv import upsert_service_account_key
from onyx.server.documents.models import GoogleAppCredentials
from onyx.server.documents.models import GoogleAppWebCredentials
from onyx.server.documents.models import GoogleServiceAccountKey


def _make_app_creds() -> GoogleAppCredentials:
    return GoogleAppCredentials(
        web=GoogleAppWebCredentials(
            client_id="client-id.apps.googleusercontent.com",
            project_id="test-project",
            auth_uri="https://accounts.google.com/o/oauth2/auth",
            token_uri="https://oauth2.googleapis.com/token",
            auth_provider_x509_cert_url="https://www.googleapis.com/oauth2/v1/certs",
            client_secret="secret",
            redirect_uris=["https://example.com/callback"],
            javascript_origins=["https://example.com"],
        )
    )


def _make_service_account_key() -> GoogleServiceAccountKey:
    return GoogleServiceAccountKey(
        type="service_account",
        project_id="test-project",
        private_key_id="private-key-id",
        private_key="-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n",
        client_email="test@test-project.iam.gserviceaccount.com",
        client_id="123",
        auth_uri="https://accounts.google.com/o/oauth2/auth",
        token_uri="https://oauth2.googleapis.com/token",
        auth_provider_x509_cert_url="https://www.googleapis.com/oauth2/v1/certs",
        client_x509_cert_url="https://www.googleapis.com/robot/v1/metadata/x509/test",
        universe_domain="googleapis.com",
    )


def test_upsert_google_app_cred_stores_dict(monkeypatch: Any) -> None:
    stored: dict[str, Any] = {}

    class _StubKvStore:
        def store(self, key: str, value: object, encrypt: bool) -> None:
            stored["key"] = key
            stored["value"] = value
            stored["encrypt"] = encrypt

    monkeypatch.setattr(
        "onyx.connectors.google_utils.google_kv.get_kv_store", lambda: _StubKvStore()
    )

    upsert_google_app_cred(_make_app_creds(), DocumentSource.GOOGLE_DRIVE)

    assert stored["key"] == KV_GOOGLE_DRIVE_CRED_KEY
    assert stored["encrypt"] is True
    assert isinstance(stored["value"], dict)
    assert stored["value"]["web"]["client_id"] == "client-id.apps.googleusercontent.com"


def test_upsert_service_account_key_stores_dict(monkeypatch: Any) -> None:
    stored: dict[str, Any] = {}

    class _StubKvStore:
        def store(self, key: str, value: object, encrypt: bool) -> None:
            stored["key"] = key
            stored["value"] = value
            stored["encrypt"] = encrypt

    monkeypatch.setattr(
        "onyx.connectors.google_utils.google_kv.get_kv_store", lambda: _StubKvStore()
    )

    upsert_service_account_key(_make_service_account_key(), DocumentSource.GOOGLE_DRIVE)

    assert stored["key"] == KV_GOOGLE_DRIVE_SERVICE_ACCOUNT_KEY
    assert stored["encrypt"] is True
    assert isinstance(stored["value"], dict)
    assert stored["value"]["project_id"] == "test-project"


@pytest.mark.parametrize("legacy_string", [False, True])
def test_get_google_app_cred_accepts_dict_and_legacy_string(
    monkeypatch: Any, legacy_string: bool
) -> None:
    payload: dict[str, Any] = _make_app_creds().model_dump(mode="json")
    stored_value: object = (
        payload if not legacy_string else _make_app_creds().model_dump_json()
    )

    class _StubKvStore:
        def load(self, key: str) -> object:
            assert key == KV_GOOGLE_DRIVE_CRED_KEY
            return stored_value

    monkeypatch.setattr(
        "onyx.connectors.google_utils.google_kv.get_kv_store", lambda: _StubKvStore()
    )

    creds = get_google_app_cred(DocumentSource.GOOGLE_DRIVE)

    assert creds.web.client_id == "client-id.apps.googleusercontent.com"


@pytest.mark.parametrize("legacy_string", [False, True])
def test_get_service_account_key_accepts_dict_and_legacy_string(
    monkeypatch: Any, legacy_string: bool
) -> None:
    stored_value: object = (
        _make_service_account_key().model_dump(mode="json")
        if not legacy_string
        else _make_service_account_key().model_dump_json()
    )

    class _StubKvStore:
        def load(self, key: str) -> object:
            assert key == KV_GOOGLE_DRIVE_SERVICE_ACCOUNT_KEY
            return stored_value

    monkeypatch.setattr(
        "onyx.connectors.google_utils.google_kv.get_kv_store", lambda: _StubKvStore()
    )

    key = get_service_account_key(DocumentSource.GOOGLE_DRIVE)

    assert key.client_email == "test@test-project.iam.gserviceaccount.com"


@pytest.mark.parametrize("legacy_string", [False, True])
def test_get_auth_url_accepts_dict_and_legacy_string(
    monkeypatch: Any, legacy_string: bool
) -> None:
    payload = _make_app_creds().model_dump(mode="json")
    stored_value: object = (
        payload if not legacy_string else _make_app_creds().model_dump_json()
    )
    stored_state: dict[str, object] = {}

    class _StubKvStore:
        def load(self, key: str) -> object:
            assert key == KV_GOOGLE_DRIVE_CRED_KEY
            return stored_value

        def store(self, key: str, value: object, encrypt: bool) -> None:
            stored_state["key"] = key
            stored_state["value"] = value
            stored_state["encrypt"] = encrypt

    class _StubFlow:
        def authorization_url(self, prompt: str) -> tuple[str, None]:
            assert prompt == "consent"
            return "https://accounts.google.com/o/oauth2/auth?state=test-state", None

    monkeypatch.setattr(
        "onyx.connectors.google_utils.google_kv.get_kv_store", lambda: _StubKvStore()
    )

    def _from_client_config(
        _app_config: object, *, scopes: object, redirect_uri: object
    ) -> _StubFlow:
        del scopes, redirect_uri
        return _StubFlow()

    monkeypatch.setattr(
        "onyx.connectors.google_utils.google_kv.InstalledAppFlow.from_client_config",
        _from_client_config,
    )

    auth_url = get_auth_url(42, DocumentSource.GOOGLE_DRIVE)

    assert auth_url.startswith("https://accounts.google.com")
    assert stored_state["value"] == {"value": "test-state"}
    assert stored_state["encrypt"] is True
