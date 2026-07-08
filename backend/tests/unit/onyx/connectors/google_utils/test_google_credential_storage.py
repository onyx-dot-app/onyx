"""Guards Google OAuth app-credential resolution off the credential row: read
the app cred from the row, reconstruct it from the row's token blob when
absent, and restore the PKCE verifier for the callback token exchange."""

import json
from typing import Any
from typing import cast

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import KV_CRED_KEY
from onyx.connectors.google_utils.google_kv import build_service_account_creds
from onyx.connectors.google_utils.google_kv import get_auth_url
from onyx.connectors.google_utils.google_kv import update_credential_access_tokens
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_AUTHENTICATION_METHOD,
)
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_DICT_APP_CREDENTIAL_KEY,
)
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY,
)
from onyx.connectors.google_utils.shared_constants import DB_CREDENTIALS_DICT_TOKEN_KEY
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY,
)
from onyx.connectors.google_utils.shared_constants import (
    GoogleOAuthAuthenticationMethod,
)
from onyx.db.models import User
from onyx.server.documents.models import GoogleAppCredentials
from onyx.server.documents.models import GoogleAppWebCredentials
from onyx.server.documents.models import GoogleServiceAccountKey


class _StubCredentialJson:
    def __init__(self, value: dict[str, object]) -> None:
        self._value = value

    def get_value(self, apply_mask: bool) -> dict[str, object]:
        assert apply_mask is False
        return self._value.copy()


class _StubCredential:
    def __init__(self, credential_json: dict[str, object]) -> None:
        self.credential_json = _StubCredentialJson(credential_json)


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


def test_build_service_account_creds_puts_key_on_credential_row() -> None:
    key = _make_service_account_key()

    credential = build_service_account_creds(
        DocumentSource.GOOGLE_DRIVE,
        service_account_key=key,
        primary_admin_email="admin@test-project.com",
    )

    credential_json = credential.credential_json
    assert (
        credential_json[DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY]
        == key.model_dump_json()
    )
    assert credential_json[DB_CREDENTIALS_PRIMARY_ADMIN_KEY] == "admin@test-project.com"
    assert credential.source == DocumentSource.GOOGLE_DRIVE


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
        def store(self, key: str, value: object, encrypt: bool) -> None:
            stored_state["key"] = key
            stored_state["value"] = value
            stored_state["encrypt"] = encrypt

    class _StubFlow:
        code_verifier: str | None = None

        def authorization_url(self, prompt: str) -> tuple[str, None]:
            assert prompt == "consent"
            self.code_verifier = "test-verifier"
            return "https://accounts.google.com/o/oauth2/auth?state=test-state", None

    def _fetch_credential_by_id_for_user(
        credential_id: int,
        user: User,
        db_session: Session,
        get_editable: bool = True,
    ) -> _StubCredential:
        del user, db_session
        assert credential_id == 42
        assert get_editable is True
        return _StubCredential({DB_CREDENTIALS_DICT_APP_CREDENTIAL_KEY: stored_value})

    def _update_credential_json(
        credential_id: int,
        credential_json: dict[str, object],
        user: User,
        db_session: Session,
    ) -> object:
        del credential_id, credential_json, user, db_session
        raise AssertionError("update_credential_json should not be called")

    def _from_client_config(
        _app_config: object, *, scopes: object, redirect_uri: object
    ) -> _StubFlow:
        del scopes, redirect_uri
        return _StubFlow()

    monkeypatch.setattr(
        "onyx.connectors.google_utils.google_kv.fetch_credential_by_id_for_user",
        _fetch_credential_by_id_for_user,
    )
    monkeypatch.setattr(
        "onyx.connectors.google_utils.google_kv.update_credential_json",
        _update_credential_json,
    )
    monkeypatch.setattr(
        "onyx.connectors.google_utils.google_kv.get_kv_store", lambda: _StubKvStore()
    )
    monkeypatch.setattr(
        "onyx.connectors.google_utils.google_kv.InstalledAppFlow.from_client_config",
        _from_client_config,
    )

    auth_url = get_auth_url(
        42,
        DocumentSource.GOOGLE_DRIVE,
        cast(User, None),
        cast(Session, None),
    )

    assert auth_url.startswith("https://accounts.google.com")
    assert stored_state["value"] == {
        "value": "test-state",
        "code_verifier": "test-verifier",
    }
    assert stored_state["encrypt"] is True


def test_update_credential_access_tokens_restores_pkce_verifier(
    monkeypatch: Any,
) -> None:
    """The token exchange restores the PKCE verifier from the KV store."""
    captured: dict[str, Any] = {}
    payload = _make_app_creds().model_dump(mode="json")

    class _StubCreds:
        def to_json(self) -> str:
            return "{}"

    class _StubFlow:
        code_verifier: str | None = None

        def fetch_token(self, code: str) -> None:
            captured["code"] = code
            captured["code_verifier"] = self.code_verifier

        @property
        def credentials(self) -> _StubCreds:
            return _StubCreds()

    class _StubKvStore:
        def load(self, key: str) -> object:
            assert key == KV_CRED_KEY.format("42")
            return {"value": "test-state", "code_verifier": "test-verifier"}

    def _fetch_credential_by_id_for_user(
        credential_id: int,
        user: User,
        db_session: Session,
        get_editable: bool = True,
    ) -> _StubCredential:
        del user, db_session
        assert credential_id == 42
        assert get_editable is True
        return _StubCredential({DB_CREDENTIALS_DICT_APP_CREDENTIAL_KEY: payload})

    def _from_client_config(
        _app_config: object, *, scopes: object, redirect_uri: object
    ) -> _StubFlow:
        del scopes, redirect_uri
        return _StubFlow()

    def _update_credential_json(
        credential_id: int,
        credential_json: dict[str, object],
        user: User,
        db_session: Session,
    ) -> bool:
        del user, db_session
        assert credential_id == 42
        captured["new_creds_dict"] = credential_json
        return True

    monkeypatch.setattr(
        "onyx.connectors.google_utils.google_kv.fetch_credential_by_id_for_user",
        _fetch_credential_by_id_for_user,
    )
    monkeypatch.setattr(
        "onyx.connectors.google_utils.google_kv.get_kv_store", lambda: _StubKvStore()
    )
    monkeypatch.setattr(
        "onyx.connectors.google_utils.google_kv.InstalledAppFlow.from_client_config",
        _from_client_config,
    )
    monkeypatch.setattr(
        "onyx.connectors.google_utils.google_kv._get_current_oauth_user",
        lambda _creds, _source: "admin@example.com",
    )
    monkeypatch.setattr(
        "onyx.connectors.google_utils.google_kv.update_credential_json",
        _update_credential_json,
    )

    creds = update_credential_access_tokens(
        "auth-code",
        42,
        cast(User, None),
        cast(Session, None),
        DocumentSource.GOOGLE_DRIVE,
        GoogleOAuthAuthenticationMethod.UPLOADED,
    )

    assert creds is not None
    assert captured["code"] == "auth-code"
    assert captured["code_verifier"] == "test-verifier"
    assert captured["new_creds_dict"][DB_CREDENTIALS_DICT_APP_CREDENTIAL_KEY] == payload
    assert captured["new_creds_dict"][DB_CREDENTIALS_DICT_TOKEN_KEY] == "{}"
    assert (
        captured["new_creds_dict"][DB_CREDENTIALS_PRIMARY_ADMIN_KEY]
        == "admin@example.com"
    )
    assert (
        captured["new_creds_dict"][DB_CREDENTIALS_AUTHENTICATION_METHOD]
        == GoogleOAuthAuthenticationMethod.UPLOADED.value
    )


def test_get_auth_url_reconstructs_app_cred_from_token_blob(
    monkeypatch: Any,
) -> None:
    """A row carrying only a token blob rebuilds the app cred from the embedded
    client id/secret and stamps it back onto the row."""
    token_blob = json.dumps(
        {
            "client_id": "token-client-id.apps.googleusercontent.com",
            "client_secret": "token-secret",
            "refresh_token": "refresh-token",
            "token_uri": "https://oauth2.googleapis.com/token",
            "token": "access-token",
            "expiry": "2030-01-01T00:00:00Z",
        }
    )
    captured: dict[str, Any] = {}

    class _StubKvStore:
        def store(self, key: str, value: object, encrypt: bool) -> None:
            del key, value, encrypt

    class _StubFlow:
        code_verifier: str | None = None

        def authorization_url(self, prompt: str) -> tuple[str, None]:
            assert prompt == "consent"
            self.code_verifier = "test-verifier"
            return "https://accounts.google.com/o/oauth2/auth?state=test-state", None

    def _fetch_credential_by_id_for_user(
        credential_id: int,
        user: User,
        db_session: Session,
        get_editable: bool = True,
    ) -> _StubCredential:
        del user, db_session
        assert credential_id == 42
        assert get_editable is True
        return _StubCredential({DB_CREDENTIALS_DICT_TOKEN_KEY: token_blob})

    def _update_credential_json(
        credential_id: int,
        credential_json: dict[str, object],
        user: User,
        db_session: Session,
    ) -> object:
        del user, db_session
        assert credential_id == 42
        captured["credential_json"] = credential_json
        return True

    def _from_client_config(
        app_config: object, *, scopes: object, redirect_uri: object
    ) -> _StubFlow:
        del scopes, redirect_uri
        captured["app_config"] = app_config
        return _StubFlow()

    monkeypatch.setattr(
        "onyx.connectors.google_utils.google_kv.fetch_credential_by_id_for_user",
        _fetch_credential_by_id_for_user,
    )
    monkeypatch.setattr(
        "onyx.connectors.google_utils.google_kv.update_credential_json",
        _update_credential_json,
    )
    monkeypatch.setattr(
        "onyx.connectors.google_utils.google_kv.get_kv_store", lambda: _StubKvStore()
    )
    monkeypatch.setattr(
        "onyx.connectors.google_utils.google_kv.InstalledAppFlow.from_client_config",
        _from_client_config,
    )

    auth_url = get_auth_url(
        42,
        DocumentSource.GOOGLE_DRIVE,
        cast(User, None),
        cast(Session, None),
    )

    assert auth_url.startswith("https://accounts.google.com")
    reconstructed = {
        "web": {
            "client_id": "token-client-id.apps.googleusercontent.com",
            "client_secret": "token-secret",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    assert captured["app_config"] == reconstructed
    assert (
        captured["credential_json"][DB_CREDENTIALS_DICT_APP_CREDENTIAL_KEY]
        == reconstructed
    )
    assert captured["credential_json"][DB_CREDENTIALS_DICT_TOKEN_KEY] == token_blob


def test_get_auth_url_uses_app_credential_on_row_without_rewrite(
    monkeypatch: Any,
) -> None:
    payload = _make_app_creds().model_dump(mode="json")

    class _StubKvStore:
        def store(self, key: str, value: object, encrypt: bool) -> None:
            del key, value, encrypt

    class _StubFlow:
        code_verifier: str | None = None

        def authorization_url(self, prompt: str) -> tuple[str, None]:
            assert prompt == "consent"
            self.code_verifier = "test-verifier"
            return "https://accounts.google.com/o/oauth2/auth?state=test-state", None

    def _fetch_credential_by_id_for_user(
        credential_id: int,
        user: User,
        db_session: Session,
        get_editable: bool = True,
    ) -> _StubCredential:
        del user, db_session
        assert credential_id == 42
        assert get_editable is True
        return _StubCredential({DB_CREDENTIALS_DICT_APP_CREDENTIAL_KEY: payload})

    def _update_credential_json(
        credential_id: int,
        credential_json: dict[str, object],
        user: User,
        db_session: Session,
    ) -> object:
        del credential_id, credential_json, user, db_session
        raise AssertionError("update_credential_json should not be called")

    def _from_client_config(
        _app_config: object, *, scopes: object, redirect_uri: object
    ) -> _StubFlow:
        del scopes, redirect_uri
        return _StubFlow()

    monkeypatch.setattr(
        "onyx.connectors.google_utils.google_kv.fetch_credential_by_id_for_user",
        _fetch_credential_by_id_for_user,
    )
    monkeypatch.setattr(
        "onyx.connectors.google_utils.google_kv.update_credential_json",
        _update_credential_json,
    )
    monkeypatch.setattr(
        "onyx.connectors.google_utils.google_kv.get_kv_store", lambda: _StubKvStore()
    )
    monkeypatch.setattr(
        "onyx.connectors.google_utils.google_kv.InstalledAppFlow.from_client_config",
        _from_client_config,
    )

    auth_url = get_auth_url(
        42,
        DocumentSource.GOOGLE_DRIVE,
        cast(User, None),
        cast(Session, None),
    )

    assert auth_url.startswith("https://accounts.google.com")


def test_get_auth_url_errors_without_app_cred_or_token(monkeypatch: Any) -> None:
    def _fetch_credential_by_id_for_user(
        credential_id: int,
        user: User,
        db_session: Session,
        get_editable: bool = True,
    ) -> _StubCredential:
        del user, db_session
        assert credential_id == 42
        assert get_editable is True
        return _StubCredential({})

    def _update_credential_json(
        credential_id: int,
        credential_json: dict[str, object],
        user: User,
        db_session: Session,
    ) -> object:
        del credential_id, credential_json, user, db_session
        raise AssertionError("update_credential_json should not be called")

    monkeypatch.setattr(
        "onyx.connectors.google_utils.google_kv.fetch_credential_by_id_for_user",
        _fetch_credential_by_id_for_user,
    )
    monkeypatch.setattr(
        "onyx.connectors.google_utils.google_kv.update_credential_json",
        _update_credential_json,
    )

    with pytest.raises(ValueError, match="no OAuth app credential"):
        get_auth_url(
            42,
            DocumentSource.GOOGLE_DRIVE,
            cast(User, None),
            cast(Session, None),
        )
