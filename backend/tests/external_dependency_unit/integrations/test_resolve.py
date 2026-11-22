"""resolve_connection and render_headers for each sign-in mode and method."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.auth.oauth_refresher import _RefreshContext
from onyx.auth.schemas import RefreshedLoginToken
from onyx.configs.constants import ANONYMOUS_USER_UUID
from onyx.db.engine.sql_engine import get_session_with_current_tenant
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
    ConnectionSecret,
    ConnectionState,
)
from onyx.integrations.connections import (
    MissingHeaderValueError,
    integration_status,
    render_headers,
    resolve_connection,
)
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integration_helpers import make_app_integration
from tests.external_dependency_unit.integrations.conftest import (
    add_connection,
    expect_problem,
    expect_resolved,
    far_future,
    new_oauth_client,
)


def test_none_mode_runs_without_credential(
    db_session: Session,
) -> None:
    integration, _ = make_app_integration(
        db_session, auth_mode=IntegrationAuthMode.NONE, auth_method=None
    )
    resolved = expect_resolved(resolve_connection(integration, None, db_session))
    assert resolved.secret is None


def test_shared_api_key_uses_organization_row_only(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.SHARED,
        auth_method=IntegrationAuthMethod.API_KEY,
        header_template={"X-Api-Key": "{api_key}"},
    )
    user = make_test_user("shared_api_key")
    # A user row must never stand in for the organization row.
    add_connection(
        db_session, integration, user.id, ConnectionSecret(fields={"api_key": "u"})
    )
    problem = expect_problem(resolve_connection(integration, user, db_session))
    assert problem.code is ConnectionState.NOT_SET_UP
    assert problem.reason == (
        f"{integration.name} is not set up for your organization. Ask your admin."
    )

    add_connection(
        db_session, integration, None, ConnectionSecret(fields={"api_key": "org"})
    )
    resolved = expect_resolved(resolve_connection(integration, user, db_session))
    assert resolved.secret is not None
    assert render_headers(integration.header_template, resolved.secret) == {
        "X-Api-Key": "org"
    }


def test_shared_oauth2_uses_organization_token(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.SHARED,
        auth_method=IntegrationAuthMethod.OAUTH2,
        header_template={"Authorization": "Bearer {access_token}"},
        oauth_client=new_oauth_client(
            IntegrationOAuthProviderMode.MANUAL, client_id="client"
        ),
    )
    add_connection(
        db_session,
        integration,
        None,
        ConnectionSecret(access_token="org-token", token_type="Bearer"),
        expires_at=far_future(),
    )
    user = make_test_user("shared_oauth")
    resolved = expect_resolved(resolve_connection(integration, user, db_session))
    assert render_headers(integration.header_template, resolved.secret) == {
        "Authorization": "Bearer org-token"
    }


def test_individual_oauth2_uses_acting_user_row_only(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        oauth_client=new_oauth_client(
            IntegrationOAuthProviderMode.MANUAL, client_id="client"
        ),
    )
    owner = make_test_user("individual_owner")
    other = make_test_user("individual_other")
    add_connection(
        db_session, integration, owner.id, ConnectionSecret(access_token="owner")
    )
    # The organization row must never stand in for a user row.
    add_connection(db_session, integration, None, ConnectionSecret(access_token="org"))

    resolved = expect_resolved(resolve_connection(integration, owner, db_session))
    assert resolved.secret is not None
    assert resolved.secret.access_token == "owner"

    problem = expect_problem(resolve_connection(integration, other, db_session))
    assert problem.code is ConnectionState.NOT_CONNECTED


def test_individual_api_key_and_needs_reconnect(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.API_KEY,
        header_template={"Authorization": "Token {api_key}"},
    )
    user = make_test_user("individual_api_key")
    connection = add_connection(
        db_session, integration, user.id, ConnectionSecret(fields={"api_key": "k1"})
    )
    resolved = expect_resolved(resolve_connection(integration, user, db_session))
    assert render_headers(integration.header_template, resolved.secret) == {
        "Authorization": "Token k1"
    }

    mark_connection_needs_reconnect__no_commit(db_session, connection, "Key revoked")
    db_session.commit()
    problem = expect_problem(resolve_connection(integration, user, db_session))
    assert problem.code is ConnectionState.NEEDS_RECONNECT
    assert problem.reason == "Key revoked"


def test_anonymous_user_gets_no_individual_connection(
    db_session: Session,
) -> None:
    integration, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.API_KEY,
    )
    anonymous = User(id=UUID(ANONYMOUS_USER_UUID), email="anonymous@example.com")
    for acting_user in (None, anonymous):
        problem = expect_problem(
            resolve_connection(integration, acting_user, db_session)
        )
        assert problem.code is ConnectionState.NOT_CONNECTED


def _add_login_account(
    db_session: Session, user: User, *, expires_at: int, refresh_token: str | None
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
    make_test_user: MakeTestUser,
) -> None:
    integration, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.ONYX_LOGIN,
        header_template={"Authorization": "Bearer {access_token}"},
    )
    user = make_test_user("onyx_login")
    try:
        now = int(datetime.now(timezone.utc).timestamp())
        account = _add_login_account(
            db_session, user, expires_at=now + 3600, refresh_token="login-refresh"
        )
        resolved = expect_resolved(resolve_connection(integration, user, db_session))
        assert render_headers(integration.header_template, resolved.secret) == {
            "Authorization": "Bearer login-token"
        }
        # No row: onyx_login stores nothing.
        assert get_connection(db_session, integration.id, user.id) is None

        # Near expiry: refreshed with no web request.
        account.expires_at = now + 10
        db_session.commit()
        name = integration.name
        integration.name = f"{name} renamed"
        new_expiry = now + int(timedelta(hours=1).total_seconds())
        with (
            patch(
                "onyx.auth.oauth_refresher._refresh_context_for_provider",
                AsyncMock(
                    return_value=_RefreshContext(
                        token_endpoint="https://idp/token",
                        client_id="c",
                        client_secret="s",
                    )
                ),
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
            resolved = expect_resolved(
                resolve_connection(integration, user, db_session)
            )
        assert refresh_call.await_count == 1
        assert resolved.secret is not None
        assert resolved.secret.access_token == "refreshed-login"
        # The refresh does not commit the work of the caller.
        db_session.rollback()
        assert integration.name == name
        db_session.refresh(account)
        assert account.access_token == "refreshed-login"
        assert account.expires_at == new_expiry
    finally:
        db_session.rollback()
        db_session.execute(
            delete(OAuthAccount).where(OAuthAccount.__table__.c.user_id == user.id)
        )
        db_session.commit()


def test_onyx_login_reports_the_expiry_of_the_refreshed_token(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.ONYX_LOGIN,
        header_template={"Authorization": "Bearer {access_token}"},
    )
    user = make_test_user("onyx_login_refreshed_expiry")
    try:
        now = int(datetime.now(timezone.utc).timestamp())
        _add_login_account(
            db_session, user, expires_at=now + 10, refresh_token="login-refresh"
        )
        new_expiry = now + int(timedelta(hours=1).total_seconds())
        # The user of a request comes from the auth session, so its login
        # account keeps the old expiry after the refresh.
        with get_session_with_current_tenant() as auth_session:
            request_user = auth_session.get(User, user.id)
            assert request_user is not None
            assert request_user.oauth_accounts
            with (
                patch(
                    "onyx.auth.oauth_refresher._refresh_context_for_provider",
                    AsyncMock(
                        return_value=_RefreshContext(
                            token_endpoint="https://idp/token",
                            client_id="c",
                            client_secret="s",
                        )
                    ),
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
                ),
            ):
                resolved = expect_resolved(
                    resolve_connection(integration, request_user, db_session)
                )
        assert resolved.secret is not None
        assert resolved.secret.access_token == "refreshed-login"
        assert resolved.expires_at == datetime.fromtimestamp(new_expiry, timezone.utc)
    finally:
        db_session.rollback()
        db_session.execute(
            delete(OAuthAccount).where(OAuthAccount.__table__.c.user_id == user.id)
        )
        db_session.commit()


def test_onyx_login_uses_a_refreshed_token_that_has_no_expiry(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.ONYX_LOGIN,
        header_template={"Authorization": "Bearer {access_token}"},
    )
    user = make_test_user("onyx_login_no_expiry")
    try:
        now = int(datetime.now(timezone.utc).timestamp())
        _add_login_account(
            db_session, user, expires_at=now - 60, refresh_token="login-refresh"
        )
        with (
            patch(
                "onyx.auth.oauth_refresher._refresh_context_for_provider",
                AsyncMock(
                    return_value=_RefreshContext(
                        token_endpoint="https://idp/token",
                        client_id="c",
                        client_secret="s",
                    )
                ),
            ),
            patch(
                "onyx.auth.oauth_refresher._request_login_token_refresh",
                AsyncMock(
                    return_value=RefreshedLoginToken(
                        access_token="refreshed-login",
                        refresh_token="login-refresh-2",
                        expires_at=None,
                    )
                ),
            ),
        ):
            resolved = expect_resolved(
                resolve_connection(integration, user, db_session)
            )
        assert resolved.secret is not None
        assert resolved.secret.access_token == "refreshed-login"
    finally:
        db_session.rollback()
        db_session.execute(
            delete(OAuthAccount).where(OAuthAccount.__table__.c.user_id == user.id)
        )
        db_session.commit()


def test_onyx_login_account_deleted_during_the_lock_wait_needs_reconnect(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.ONYX_LOGIN,
        header_template={"Authorization": "Bearer {access_token}"},
    )
    user = make_test_user("onyx_login_deleted")
    try:
        now = int(datetime.now(timezone.utc).timestamp())
        # Near expiry, but not expired: the old token would still pass.
        _add_login_account(
            db_session, user, expires_at=now + 30, refresh_token="login-refresh"
        )

        @contextmanager
        def lock_after_the_account_is_deleted(
            *_: object, **__: object
        ) -> Iterator[None]:
            with get_session_with_current_tenant() as other_session:
                other_session.execute(
                    delete(OAuthAccount).where(
                        OAuthAccount.__table__.c.user_id == user.id
                    )
                )
                other_session.commit()
            yield

        with patch(
            "onyx.integrations.connections.cache_shared_lock",
            lock_after_the_account_is_deleted,
        ):
            result = expect_problem(resolve_connection(integration, user, db_session))

        assert result.code is ConnectionState.NEEDS_RECONNECT
    finally:
        db_session.rollback()
        db_session.execute(
            delete(OAuthAccount).where(OAuthAccount.__table__.c.user_id == user.id)
        )
        db_session.commit()


def test_onyx_login_status_of_an_expired_token_without_refresh_needs_reconnect(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.ONYX_LOGIN,
    )
    user = make_test_user("onyx_login_expired")
    try:
        now = int(datetime.now(timezone.utc).timestamp())
        _add_login_account(db_session, user, expires_at=now - 60, refresh_token=None)

        status = integration_status(integration, user, db_session)
        result = expect_problem(resolve_connection(integration, user, db_session))

        assert result.code is ConnectionState.NEEDS_RECONNECT
        assert (status.state, status.reason) == (result.code, result.reason)
    finally:
        db_session.rollback()
        db_session.execute(
            delete(OAuthAccount).where(OAuthAccount.__table__.c.user_id == user.id)
        )
        db_session.commit()


def test_onyx_login_without_a_login_account_is_not_connected(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.ONYX_LOGIN,
    )
    user = make_test_user("onyx_login_no_account")

    result = expect_problem(resolve_connection(integration, user, db_session))
    assert result.code is ConnectionState.NOT_CONNECTED
    status = integration_status(integration, user, db_session)
    assert (status.state, status.reason) == (result.code, result.reason)


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
    assert render_headers({"X-Static": "a{{b}}c"}, None) == {"X-Static": "a{b}c"}
    assert render_headers(
        {"X-Mixed": "{{{api_key}}}"}, ConnectionSecret(fields={"api_key": "k"})
    ) == {"X-Mixed": "{k}"}
