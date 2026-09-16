import base64
import json
from collections.abc import Callable
from types import ModuleType
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.responses import JSONResponse
from starlette.requests import Request

from ee.onyx.server.oauth import api as connector_api
from ee.onyx.server.oauth import confluence_cloud, google_drive, slack
from onyx.configs.constants import DocumentSource
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.federated_connectors.oauth_utils import OAuthSession
from onyx.server.features.oauth_config import api as config_api
from onyx.server.features.oauth_config.models import (
    OAuthConfigCreate,
    OAuthConfigUpdate,
)
from onyx.server.federated import api as federated_api


@pytest.mark.parametrize(
    "redirect",
    [
        "javascript:alert(1)",
        "https://example.com",
        "//example.com",
        "/\\example.com",
        "/\n/example.com",
        "/\t/example.com",
    ],
)
def test_connector_redirect_stays_on_site(redirect: str) -> None:
    with patch.object(connector_api, "get_redis_client") as redis:
        with pytest.raises(OnyxError) as error:
            connector_api.prepare_authorization_request(
                DocumentSource.SLACK,
                redirect,
                User(id=uuid4(), email="owner@example.com"),
                "public",
            )
        assert error.value.error_code == OnyxErrorCode.INVALID_INPUT
        redis.assert_not_called()
        with (
            patch.object(
                connector_api.SlackOAuth,
                "generate_oauth_url",
                return_value="https://example.com/authorize",
            ),
            patch.object(connector_api, "DEV_MODE", False),
        ):
            connector_api.prepare_authorization_request(
                DocumentSource.SLACK,
                "/admin/connectors?done=1",
                User(id=uuid4(), email="owner@example.com"),
                "public",
            )
        redis.return_value.set.assert_called_once()


@pytest.mark.parametrize(
    "module,callback,provider",
    [
        (slack, slack.handle_slack_oauth_callback, slack.SlackOAuth),
        (
            google_drive,
            google_drive.handle_google_drive_oauth_callback,
            google_drive.GoogleDriveOAuth,
        ),
        (
            confluence_cloud,
            confluence_cloud.confluence_oauth_callback,
            confluence_cloud.ConfluenceCloudOAuth,
        ),
    ],
)
def test_connector_callback_checks_owner(
    module: ModuleType,
    callback: Callable[..., JSONResponse],
    provider: type[slack.SlackOAuth]
    | type[google_drive.GoogleDriveOAuth]
    | type[confluence_cloud.ConfluenceCloudOAuth],
) -> None:
    state = base64.urlsafe_b64encode(uuid4().bytes).decode().rstrip("=")
    owner = uuid4()
    session = provider.session_dump_json(
        email="owner@example.com", redirect_on_success="/admin", user_id=owner
    )
    with (
        patch.object(module, "get_redis_client") as redis,
        patch.object(provider, "CLIENT_ID", "test-client"),
        patch.object(provider, "CLIENT_SECRET", "test-secret"),
        patch.object(
            module.requests, "post", side_effect=RuntimeError("exchange reached")
        ) as exchange,
    ):
        redis.return_value.get.return_value = session.encode()
        with pytest.raises(OnyxError) as error:
            callback(
                code="code",
                state=state,
                user=User(id=uuid4(), email="owner@example.com"),
                db_session=MagicMock(),
                tenant_id="public",
            )
        assert error.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
        exchange.assert_not_called()
        redis.return_value.delete.assert_not_called()
        callback(
            code="code",
            state=state,
            user=User(id=owner, email="changed@example.com"),
            db_session=MagicMock(),
            tenant_id="public",
        )
        exchange.assert_called_once()
        exchange.reset_mock()
        legacy_session = json.loads(session)
        del legacy_session["user_id"]
        redis.return_value.get.return_value = json.dumps(legacy_session).encode()
        with pytest.raises(OnyxError) as error:
            callback(
                code="code",
                state=state,
                user=User(id=owner, email="owner@example.com"),
                db_session=MagicMock(),
                tenant_id="public",
            )
        assert error.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
        exchange.assert_not_called()


@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize("field", ["authorization_url", "token_url"])
@pytest.mark.parametrize("url", ["javascript:alert(1)", "http://example.com/token", ""])
def test_oauth_config_rejects_unsafe_endpoint(
    operation: str, field: str, url: str
) -> None:
    user = User(id=uuid4(), email="owner@example.com")
    data = {
        "name": "test",
        "authorization_url": "https://example.com/auth",
        "token_url": "https://example.com/token",
        "client_id": "test-client",
        "client_secret": "test-secret",
    }
    data[field] = url
    with (
        patch.object(
            config_api, "get_oauth_config", return_value=MagicMock(created_by=user.id)
        ),
        patch.object(config_api, "_assert_can_manage_oauth_config"),
        patch.object(
            config_api, "create_oauth_config", side_effect=RuntimeError("write reached")
        ) as create,
        patch.object(
            config_api, "update_oauth_config", side_effect=RuntimeError("write reached")
        ) as update,
        patch("onyx.auth.oauth_token_manager.get_security_settings"),
    ):
        with pytest.raises(OnyxError) as error:
            if operation == "create":
                config_api.create_oauth_config_endpoint(
                    OAuthConfigCreate.model_validate(data),
                    db_session=MagicMock(),
                    _=user,
                )
            else:
                config_api.update_oauth_config_endpoint(
                    1,
                    OAuthConfigUpdate.model_validate(data),
                    db_session=MagicMock(),
                    user=user,
                )
        assert error.value.error_code == OnyxErrorCode.INVALID_INPUT
        create.assert_not_called()
        update.assert_not_called()
        data[field] = "https://example.com/oauth"
        with pytest.raises(RuntimeError, match="write reached"):
            if operation == "create":
                config_api.create_oauth_config_endpoint(
                    OAuthConfigCreate.model_validate(data), MagicMock(), user
                )
            else:
                config_api.update_oauth_config_endpoint(
                    1, OAuthConfigUpdate.model_validate(data), MagicMock(), user
                )


def test_federated_callback_checks_owner() -> None:
    owner = uuid4()
    request = Request({"type": "http", "query_string": b"state=test&code=code"})
    with (
        patch.object(
            federated_api,
            "verify_oauth_state",
            return_value=OAuthSession(1, str(owner)),
        ),
        patch.object(
            federated_api,
            "fetch_federated_connector_by_id",
            side_effect=RuntimeError("lookup reached"),
        ) as lookup,
    ):
        with pytest.raises(OnyxError) as error:
            federated_api.handle_oauth_callback_generic(
                request, User(id=uuid4()), MagicMock()
            )
        assert error.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
        lookup.assert_not_called()
        with pytest.raises(RuntimeError, match="lookup reached"):
            federated_api.handle_oauth_callback_generic(
                request, User(id=owner), MagicMock()
            )


@pytest.mark.parametrize("field", ["authorization_url", "token_url"])
def test_oauth_config_partial_update_validates_retained_urls(field: str) -> None:
    config = MagicMock(
        authorization_url="https://example.com/auth",
        token_url="https://example.com/token",
    )
    config.__dict__[field] = "javascript:alert(1)"
    with (
        patch.object(config_api, "get_oauth_config", return_value=config),
        patch.object(config_api, "_assert_can_manage_oauth_config"),
        patch.object(
            config_api, "update_oauth_config", side_effect=RuntimeError("write reached")
        ) as update,
        patch("onyx.auth.oauth_token_manager.get_security_settings"),
    ):
        with pytest.raises(OnyxError) as error:
            config_api.update_oauth_config_endpoint(
                1, OAuthConfigUpdate(name="renamed"), MagicMock(), User(id=uuid4())
            )
        assert error.value.error_code == OnyxErrorCode.INVALID_INPUT
        update.assert_not_called()
        config.__dict__[field] = "https://example.com/fixed"
        with pytest.raises(RuntimeError, match="write reached"):
            config_api.update_oauth_config_endpoint(
                1, OAuthConfigUpdate(name="renamed"), MagicMock(), User(id=uuid4())
            )
