"""Salesforce OAuth route coverage with real tenant Redis and PostgreSQL."""

from typing import Any
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import UUID

import pytest
from fastapi import Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    get_oauth_callback_uri,
)
from onyx.connectors.salesforce import auth as salesforce_auth
from onyx.connectors.salesforce import connector as salesforce_connector
from onyx.connectors.salesforce.models import SalesforceAuthenticationMethod
from onyx.db.models import Credential
from onyx.error_handling.exceptions import OnyxError
from onyx.redis.redis_pool import get_redis_client
from onyx.server.documents import standard_oauth
from onyx.server.documents.standard_oauth import OAuthState
from onyx.utils.sensitive import SensitiveValue
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user

_CLIENT_ID = "salesforce-edu-client"
_CLIENT_SECRET = "salesforce-edu-secret"
_MY_DOMAIN_URL = "https://onyx-edu.my.salesforce.com"
_INSTANCE_URL = "https://na123.salesforce.com"
_AUTHORIZATION_CODE = "salesforce-edu-authorization-code"
_ACCESS_TOKEN = "salesforce-edu-access-token"
_REFRESH_TOKEN = "salesforce-edu-refresh-token"
_RETURN_URL = "https://onyx.example/admin/connectors/salesforce?step=0"
_STATE_KEY_PREFIX = "oauth_state:"
_INVALID_STATE = UUID("00000000-0000-0000-0000-000000000005")


def _request(query_params: dict[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/connector/oauth/authorize/salesforce",
            "headers": [],
            "query_string": urlencode(query_params).encode(),
        }
    )


def _token_response() -> MagicMock:
    response = MagicMock()
    response.ok = True
    response.json.return_value = {
        "access_token": _ACCESS_TOKEN,
        "refresh_token": _REFRESH_TOKEN,
        "instance_url": _INSTANCE_URL,
    }
    return response


def _configure_salesforce_oauth(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    monkeypatch.setattr(salesforce_connector, "SALESFORCE_CLIENT_ID", _CLIENT_ID)
    monkeypatch.setattr(
        salesforce_connector, "SALESFORCE_CLIENT_SECRET", _CLIENT_SECRET
    )
    monkeypatch.setattr(salesforce_auth, "SALESFORCE_CLIENT_ID", _CLIENT_ID)
    monkeypatch.setattr(salesforce_auth, "SALESFORCE_CLIENT_SECRET", _CLIENT_SECRET)
    token_request = MagicMock(return_value=_token_response())
    monkeypatch.setattr(salesforce_auth, "request_with_retries", token_request)
    return token_request


def _state_key(state: str) -> str:
    return f"{_STATE_KEY_PREFIX}{state}"


def _raw_tenant_state_key(state: str) -> str:
    return f"{get_current_tenant_id()}:{_state_key(state)}"


def _credential_json(credential: Credential) -> dict[str, Any]:
    assert isinstance(credential.credential_json, SensitiveValue)
    return credential.credential_json.get_value(apply_mask=False)


@pytest.mark.usefixtures("tenant_context")
def test_salesforce_standard_oauth_real_redis_postgres_flow(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token_request = _configure_salesforce_oauth(monkeypatch)
    admin_user = create_test_user(db_session, "salesforce_oauth_admin", is_admin=True)
    redis_client = get_redis_client()
    credential_id: int | None = None
    state: str | None = None

    try:
        details = standard_oauth.oauth_details(
            source=DocumentSource.SALESFORCE,
            _=admin_user,
        )
        assert details.oauth_enabled is True
        assert details.supports_manual_credentials is True
        assert [item.model_dump() for item in details.additional_kwargs] == [
            {
                "name": "salesforce_my_domain_url",
                "display_name": "Salesforce My Domain URL",
                "description": (
                    "Your Salesforce My Domain URL, such as "
                    "https://company.my.salesforce.com."
                ),
            }
        ]

        authorize_response = standard_oauth.oauth_authorize(
            request=_request({"salesforce_my_domain_url": _MY_DOMAIN_URL}),
            source=DocumentSource.SALESFORCE,
            desired_return_url=_RETURN_URL,
            _=admin_user,
        )
        authorization_url = urlsplit(authorize_response.redirect_url)
        authorization_query = parse_qs(authorization_url.query)
        state = authorization_query["state"][0]

        assert f"{authorization_url.scheme}://{authorization_url.netloc}" == (
            _MY_DOMAIN_URL
        )
        assert authorization_url.path == "/services/oauth2/authorize"
        assert authorization_query["client_id"] == [_CLIENT_ID]
        assert authorization_query["scope"] == ["api refresh_token"]
        assert authorization_query["code_challenge_method"] == ["S256"]
        assert authorization_query["redirect_uri"] == [
            get_oauth_callback_uri(
                standard_oauth.WEB_DOMAIN, DocumentSource.SALESFORCE.value
            )
        ]

        stored_bytes = redis_client.raw_client.get(_raw_tenant_state_key(state))
        assert isinstance(stored_bytes, bytes)
        stored_state = OAuthState.model_validate_json(stored_bytes)
        assert stored_state.desired_return_url == _RETURN_URL
        assert stored_state.additional_kwargs == {
            "salesforce_my_domain_url": _MY_DOMAIN_URL
        }
        assert stored_state.code_verifier

        callback_response = standard_oauth.oauth_callback(
            source=DocumentSource.SALESFORCE,
            code=_AUTHORIZATION_CODE,
            state=state,
            db_session=db_session,
            user=admin_user,
        )
        credential_id = int(
            parse_qs(urlsplit(callback_response.redirect_url).query)["credentialId"][0]
        )
        db_session.expire_all()
        credential = db_session.get(Credential, credential_id)
        assert credential is not None
        assert credential.source == DocumentSource.SALESFORCE
        assert credential.user_id == admin_user.id
        assert credential.admin_public is True
        assert credential.name == "Salesforce OAuth Credential"
        assert _credential_json(credential) == {
            "authentication_method": SalesforceAuthenticationMethod.OAUTH,
            "sf_access_token": _ACCESS_TOKEN,
            "sf_refresh_token": _REFRESH_TOKEN,
            "sf_instance_url": _INSTANCE_URL,
            "sf_login_url": _MY_DOMAIN_URL,
        }

        encrypted_value = db_session.execute(
            text("SELECT credential_json FROM credential WHERE id = :credential_id"),
            {"credential_id": credential_id},
        ).scalar_one()
        assert _ACCESS_TOKEN not in str(encrypted_value)
        assert redis_client.raw_client.get(_raw_tenant_state_key(state)) is None

        request_data = token_request.call_args.kwargs["data"]
        assert set(request_data) == {
            "grant_type",
            "code",
            "client_id",
            "client_secret",
            "redirect_uri",
            "code_verifier",
        }
        assert request_data["grant_type"] == "authorization_code"
        assert request_data["code"] == _AUTHORIZATION_CODE
        assert request_data["client_id"] == _CLIENT_ID
        assert request_data["client_secret"] == _CLIENT_SECRET
        assert request_data["redirect_uri"] == authorization_query["redirect_uri"][0]
        assert request_data["code_verifier"] == stored_state.code_verifier
        assert token_request.call_args.kwargs["log_request_data"] is False

        with pytest.raises(OnyxError, match="Invalid OAuth state"):
            standard_oauth.oauth_callback(
                source=DocumentSource.SALESFORCE,
                code=_AUTHORIZATION_CODE,
                state=state,
                db_session=db_session,
                user=admin_user,
            )
        token_request.assert_called_once()
    finally:
        if state is not None:
            redis_client.delete(_state_key(state))
        if credential_id is not None:
            credential = db_session.get(Credential, credential_id)
            if credential is not None:
                db_session.delete(credential)
        delete_test_user(db_session, admin_user)
        db_session.commit()


@pytest.mark.usefixtures("tenant_context")
def test_salesforce_standard_oauth_invalid_domain_and_disabled_config(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_salesforce_oauth(monkeypatch)
    admin_user = create_test_user(
        db_session, "salesforce_oauth_disabled_admin", is_admin=True
    )
    redis_client = get_redis_client()
    invalid_state_key = _state_key(str(_INVALID_STATE))
    redis_client.delete(invalid_state_key)

    try:
        monkeypatch.setattr(standard_oauth.uuid, "uuid4", lambda: _INVALID_STATE)
        with pytest.raises(OnyxError, match="Salesforce URL must use HTTPS"):
            standard_oauth.oauth_authorize(
                request=_request(
                    {
                        # http:// so the URL parses and the HTTPS check rejects it.
                        "salesforce_my_domain_url": (
                            "http://danswer-dev-ed.develop.my.salesforce.com"
                        )
                    }
                ),
                source=DocumentSource.SALESFORCE,
                desired_return_url=_RETURN_URL,
                _=admin_user,
            )
        assert (
            redis_client.raw_client.get(_raw_tenant_state_key(str(_INVALID_STATE)))
            is None
        )

        monkeypatch.setattr(salesforce_connector, "SALESFORCE_CLIENT_SECRET", None)
        monkeypatch.setattr(salesforce_auth, "SALESFORCE_CLIENT_SECRET", None)
        details = standard_oauth.oauth_details(
            source=DocumentSource.SALESFORCE,
            _=admin_user,
        )
        assert details.oauth_enabled is False
        assert details.supports_manual_credentials is True
        with pytest.raises(OnyxError, match="OAuth is not configured"):
            standard_oauth.oauth_authorize(
                request=_request({"salesforce_my_domain_url": _MY_DOMAIN_URL}),
                source=DocumentSource.SALESFORCE,
                desired_return_url=_RETURN_URL,
                _=admin_user,
            )
        assert (
            redis_client.raw_client.get(_raw_tenant_state_key(str(_INVALID_STATE)))
            is None
        )
    finally:
        redis_client.delete(invalid_state_key)
        delete_test_user(db_session, admin_user)
        db_session.commit()
