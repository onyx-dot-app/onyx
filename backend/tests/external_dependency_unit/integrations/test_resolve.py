"""resolve_connection and render_headers for each sign-in mode and method."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.auth.oauth_refresher import RefreshedLoginToken, _RefreshContext
from onyx.configs.constants import ANONYMOUS_USER_UUID
from onyx.db.enums import (
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationOAuthProviderMode,
)
from onyx.db.integration_connection import (
    get_connection,
    mark_connection_needs_reconnect__no_commit,
)
from onyx.db.models import OAuthAccount, User
from onyx.integrations.connection_models import (
    ConnectionProblemCode,
    ConnectionSecret,
)
from onyx.integrations.connections import (
    ConnectionProblem,
    MissingHeaderValueError,
    ResolvedConnection,
    render_headers,
    resolve_connection,
)
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integrations.conftest import (
    MakeIntegration,
    add_connection,
    far_future,
)


def _resolved(result: ResolvedConnection | ConnectionProblem) -> ResolvedConnection:
    if not isinstance(result, ResolvedConnection):
        pytest.fail(f"expected a connection, got {result}")
    return result


def _problem(result: ResolvedConnection | ConnectionProblem) -> ConnectionProblem:
    if not isinstance(result, ConnectionProblem):
        pytest.fail(f"expected a problem, got {result}")
    return result


def test_none_mode_runs_without_credential(
    db_session: Session, make_integration: MakeIntegration
) -> None:
    integration = make_integration(auth_mode=IntegrationAuthMode.NONE, auth_method=None)
    resolved = _resolved(resolve_connection(integration, None, db_session))
    assert resolved.secret is None


def test_shared_api_key_uses_organization_row_only(
    db_session: Session,
    make_integration: MakeIntegration,
    make_test_user: MakeTestUser,
) -> None:
    integration = make_integration(
        auth_mode=IntegrationAuthMode.SHARED,
        auth_method=IntegrationAuthMethod.API_KEY,
        header_template={"X-Api-Key": "{api_key}"},
    )
    user = make_test_user("shared_api_key")
    # A user row must never stand in for the organization row.
    add_connection(
        db_session, integration, user.id, ConnectionSecret(fields={"api_key": "u"})
    )
    problem = _problem(resolve_connection(integration, user, db_session))
    assert problem.code is ConnectionProblemCode.NOT_SET_UP
    assert problem.reason == (
        f"{integration.name} is not set up for your organization. Ask your admin."
    )

    add_connection(
        db_session, integration, None, ConnectionSecret(fields={"api_key": "org"})
    )
    resolved = _resolved(resolve_connection(integration, user, db_session))
    assert resolved.secret is not None
    assert render_headers(integration.header_template, resolved.secret) == {
        "X-Api-Key": "org"
    }


def test_shared_oauth2_uses_organization_token(
    db_session: Session,
    make_integration: MakeIntegration,
    make_test_user: MakeTestUser,
) -> None:
    integration = make_integration(
        auth_mode=IntegrationAuthMode.SHARED,
        auth_method=IntegrationAuthMethod.OAUTH2,
        header_template={"Authorization": "Bearer {access_token}"},
        provider_mode=IntegrationOAuthProviderMode.MANUAL,
        client_id="client",
    )
    add_connection(
        db_session,
        integration,
        None,
        ConnectionSecret(access_token="org-token", token_type="Bearer"),
        expires_at=far_future(),
    )
    user = make_test_user("shared_oauth")
    resolved = _resolved(resolve_connection(integration, user, db_session))
    assert render_headers(integration.header_template, resolved.secret) == {
        "Authorization": "Bearer org-token"
    }


def test_individual_oauth2_uses_acting_user_row_only(
    db_session: Session,
    make_integration: MakeIntegration,
    make_test_user: MakeTestUser,
) -> None:
    integration = make_integration(
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        provider_mode=IntegrationOAuthProviderMode.MANUAL,
        client_id="client",
    )
    owner = make_test_user("individual_owner")
    other = make_test_user("individual_other")
    add_connection(
        db_session, integration, owner.id, ConnectionSecret(access_token="owner")
    )
    # The organization row must never stand in for a user row.
    add_connection(db_session, integration, None, ConnectionSecret(access_token="org"))

    resolved = _resolved(resolve_connection(integration, owner, db_session))
    assert resolved.secret is not None
    assert resolved.secret.access_token == "owner"

    problem = _problem(resolve_connection(integration, other, db_session))
    assert problem.code is ConnectionProblemCode.NOT_CONNECTED


def test_individual_api_key_and_needs_reconnect(
    db_session: Session,
    make_integration: MakeIntegration,
    make_test_user: MakeTestUser,
) -> None:
    integration = make_integration(
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.API_KEY,
        header_template={"Authorization": "Token {api_key}"},
    )
    user = make_test_user("individual_api_key")
    connection = add_connection(
        db_session, integration, user.id, ConnectionSecret(fields={"api_key": "k1"})
    )
    resolved = _resolved(resolve_connection(integration, user, db_session))
    assert render_headers(integration.header_template, resolved.secret) == {
        "Authorization": "Token k1"
    }

    mark_connection_needs_reconnect__no_commit(db_session, connection, "Key revoked")
    db_session.commit()
    problem = _problem(resolve_connection(integration, user, db_session))
    assert problem.code is ConnectionProblemCode.NEEDS_RECONNECT
    assert problem.reason == "Key revoked"


def test_anonymous_user_gets_no_individual_connection(
    db_session: Session, make_integration: MakeIntegration
) -> None:
    integration = make_integration(
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.API_KEY,
    )
    anonymous = User(id=UUID(ANONYMOUS_USER_UUID), email="anonymous@example.com")
    for acting_user in (None, anonymous):
        problem = _problem(resolve_connection(integration, acting_user, db_session))
        assert problem.code is ConnectionProblemCode.NOT_CONNECTED


def _add_login_account(
    db_session: Session, user: User, *, expires_at: int, refresh_token: str
) -> OAuthAccount:
    account = OAuthAccount(
        user_id=user.id,
        oauth_name="test-idp",
        account_id=f"acct-{user.id}",
        account_email=user.email,
        access_token="login-token",
        refresh_token=refresh_token,
        expires_at=expires_at,
    )
    db_session.add(account)
    db_session.commit()
    db_session.refresh(user)
    return account


def test_onyx_login_uses_and_refreshes_login_token(
    db_session: Session,
    make_integration: MakeIntegration,
    make_test_user: MakeTestUser,
) -> None:
    integration = make_integration(
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.ONYX_LOGIN,
        header_template={"Authorization": "Bearer {access_token}"},
    )
    user = make_test_user("onyx_login")
    try:
        problem = _problem(resolve_connection(integration, user, db_session))
        assert problem.code is ConnectionProblemCode.NEEDS_RECONNECT

        now = int(datetime.now(timezone.utc).timestamp())
        account = _add_login_account(
            db_session, user, expires_at=now + 3600, refresh_token="login-refresh"
        )
        resolved = _resolved(resolve_connection(integration, user, db_session))
        assert render_headers(integration.header_template, resolved.secret) == {
            "Authorization": "Bearer login-token"
        }
        # No row: onyx_login stores nothing.
        assert get_connection(db_session, integration.id, user.id) is None

        # Near expiry: refreshed with no web request.
        account.expires_at = now + 10
        db_session.commit()
        new_expiry = now + int(timedelta(hours=1).total_seconds())
        with (
            patch(
                "onyx.auth.oauth_refresher._refresh_context_for_provider",
                AsyncMock(return_value=_RefreshContext("https://idp/token", "c", "s")),
            ),
            patch(
                "onyx.auth.oauth_refresher._request_login_token_refresh",
                AsyncMock(
                    return_value=RefreshedLoginToken(
                        access_token="refreshed-login",
                        refresh_token="login-refresh-2",
                        expires_at=new_expiry,
                    )
                ),
            ) as refresh_call,
        ):
            resolved = _resolved(resolve_connection(integration, user, db_session))
        assert refresh_call.await_count == 1
        assert resolved.secret is not None
        assert resolved.secret.access_token == "refreshed-login"
        db_session.refresh(account)
        assert account.access_token == "refreshed-login"
        assert account.expires_at == new_expiry
    finally:
        db_session.rollback()
        db_session.execute(
            delete(OAuthAccount).where(OAuthAccount.__table__.c.user_id == user.id)
        )
        db_session.commit()


def test_render_headers_fills_and_refuses() -> None:
    secret = ConnectionSecret(
        access_token="tok", token_type="Bearer", fields={"tenant": "acme"}
    )
    assert render_headers(
        {
            "Authorization": "{token_type} {access_token}",
            "X-Tenant": "{tenant}",
            "X-User": "{user_email}",
            "X-Static": "fixed",
        },
        secret,
        extra_values={"user_email": "a@example.com"},
    ) == {
        "Authorization": "Bearer tok",
        "X-Tenant": "acme",
        "X-User": "a@example.com",
        "X-Static": "fixed",
    }

    with pytest.raises(MissingHeaderValueError) as error:
        render_headers({"Authorization": "Bearer {access_token}"}, ConnectionSecret())
    assert error.value.placeholders == ["access_token"]

    with pytest.raises(MissingHeaderValueError):
        render_headers({"X-Key": "{api_key}"}, None)

    assert render_headers(None, None) == {}
