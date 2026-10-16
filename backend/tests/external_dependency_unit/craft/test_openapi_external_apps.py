"""OpenAPI actions own their Craft gateway and its credential lifecycle."""

from collections.abc import Generator
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from onyx.auth.permissions import Permission
from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import EndpointPolicy, GatedAppKind
from onyx.db.external_app import (
    sync_openapi_external_app__no_commit,
    upsert_external_app_user_credential,
)
from onyx.db.gated_app import (
    get_action_policies,
    get_or_create_gated_app_id,
    replace_action_policies__no_commit,
)
from onyx.db.models import ExternalApp, OAuthAccount, OAuthConfig, Tool, User
from onyx.db.oauth_config import (
    create_oauth_config,
    delete_user_oauth_token,
    get_oauth_config,
    upsert_user_oauth_token,
)
from onyx.db.tools import get_tool_by_id, get_tools_by_ids
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError, register_onyx_exception_handlers
from onyx.external_apps.credentials import (
    ExternalAppCredentialsError,
    app_is_available,
    resolve_injection_headers,
)
from onyx.external_apps.matching.engine import (
    apply_credential_gate,
    recognize_actions,
    resolve_app_for_url,
)
from onyx.external_apps.matching.request import ProxiedRequest
from onyx.server.features.build.external_apps.api import (
    admin_router,
    delete_external_app_admin,
    list_external_apps,
    list_external_apps_admin,
    update_external_app_admin,
    upsert_user_credentials,
)
from onyx.server.features.build.external_apps.models import (
    UpdateExternalAppRequest,
    UpsertUserCredentialsRequest,
)
from onyx.server.features.oauth_config.api import (
    delete_oauth_config_endpoint,
    update_oauth_config_endpoint,
)
from onyx.server.features.oauth_config.models import OAuthConfigUpdate
from onyx.server.features.tool.api import (
    ToolStatusUpdateRequest,
    create_custom_tool,
    delete_custom_tool,
    update_custom_tool,
    update_tools_status,
)
from onyx.server.features.tool.models import CustomToolCreate, CustomToolUpdate, Header
from onyx.utils.encryption import is_masked_credential
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user

_SECRET = "Bearer secret-with-{literal}-braces"


def _schema(base: str = "https://openapi-test.example.com/v1") -> dict[str, Any]:
    return {
        "openapi": "3.0.0",
        "info": {
            "title": "Craft lifecycle",
            "version": "1.0",
            "description": "Test lifecycle",
        },
        "servers": [{"url": base}],
        "paths": {
            "/records": {
                "get": {
                    "operationId": "list_records",
                    "summary": "List records",
                    "responses": {"200": {"description": "Records"}},
                }
            }
        },
    }


@pytest.fixture
def action_admin(db_session: Session) -> Generator[User, None, None]:
    user = create_test_user(db_session, "openapi_craft", assign_default_group=False)
    user.effective_permissions = [Permission.FULL_ADMIN_PANEL_ACCESS.value]
    db_session.commit()
    yield user
    db_session.rollback()
    db_session.execute(delete(Tool).where(Tool.user_id == user.id))
    delete_test_user(db_session, user)
    db_session.commit()


@pytest.fixture
def other_user(db_session: Session) -> Generator[User, None, None]:
    user = create_test_user(
        db_session, "openapi_craft_other", assign_default_group=False
    )
    yield user
    db_session.rollback()
    db_session.execute(
        delete(OAuthAccount).where(OAuthAccount.__table__.c.user_id == user.id)
    )
    delete_test_user(db_session, user)
    db_session.commit()


@pytest.fixture
def oauth_config(db_session: Session) -> Generator[OAuthConfig, None, None]:
    config = create_oauth_config(
        name=f"craft-oauth-{uuid4().hex}",
        authorization_url="https://auth.example.com/authorize",
        token_url="https://auth.example.com/token",
        client_id="test-client",
        client_secret="test-secret",
        scopes=None,
        additional_params=None,
        db_session=db_session,
    )
    config_id = config.id
    yield config
    db_session.rollback()
    db_session.execute(delete(OAuthConfig).where(OAuthConfig.id == config_id))
    db_session.commit()


def _create(db_session: Session, user: User, *, enabled: bool = True) -> int:
    return create_custom_tool(
        CustomToolCreate(
            name="Craft lifecycle",
            definition=_schema(),
            passthrough_auth=False,
            available_in_craft=enabled,
            custom_headers=[Header(key="Authorization", value=_SECRET)],
        ),
        db_session=db_session,
        user=user,
    ).id


def _app(db_session: Session, tool_id: int) -> ExternalApp:
    app = db_session.scalar(
        select(ExternalApp).where(ExternalApp.openapi_tool_id == tool_id)
    )
    assert app is not None
    return app


def test_linked_gateway_updates_secrets_urls_and_lifecycle(
    db_session: Session, action_admin: User
) -> None:
    tool_id = _create(db_session, action_admin)
    app = _app(db_session, tool_id)
    app_id = app.id
    assert app.enabled
    assert app.associated_skills == []
    assert resolve_injection_headers(db_session, app.id, action_admin.id) == {
        "Authorization": _SECRET
    }
    assert (
        resolve_app_for_url("https://openapi-test.example.com/v1/records", [app]) is app
    )
    assert (
        resolve_app_for_url("https://openapi-test.example.com/v10/records", [app])
        is None
    )
    assert (
        resolve_app_for_url("https://openapi-test.example.com.evil/v1/records", [app])
        is None
    )

    snapshot = update_custom_tool(
        tool_id, CustomToolUpdate(name="Renamed"), db_session, action_admin
    )
    assert snapshot.custom_headers is not None
    masked = snapshot.custom_headers[0]["value"]
    assert is_masked_credential(masked)
    update_custom_tool(
        tool_id,
        CustomToolUpdate(
            definition=_schema("https://openapi-test.example.com/v2"),
            custom_headers=[Header(key="Authorization", value=masked)],
        ),
        db_session,
        action_admin,
    )
    db_session.expire_all()
    app = _app(db_session, tool_id)
    assert app.id == app_id
    assert app.name == "Renamed"
    assert (
        resolve_app_for_url("https://openapi-test.example.com/v1/records", [app])
        is None
    )
    assert (
        resolve_app_for_url("https://openapi-test.example.com/v2/records", [app]) is app
    )
    assert resolve_injection_headers(db_session, app.id, action_admin.id) == {
        "Authorization": _SECRET
    }

    for enabled in (False, True):
        update_tools_status(
            ToolStatusUpdateRequest(tool_ids=[tool_id], enabled=enabled),
            db_session,
            action_admin,
        )
        db_session.expire_all()
        assert _app(db_session, tool_id).enabled is enabled

    update_custom_tool(
        tool_id, CustomToolUpdate(available_in_craft=False), db_session, action_admin
    )
    assert not _app(db_session, tool_id).enabled
    assert resolve_injection_headers(db_session, app_id, action_admin.id) == {}
    update_custom_tool(
        tool_id,
        CustomToolUpdate(name="Renamed while unavailable"),
        db_session,
        action_admin,
    )
    db_session.expire_all()
    response = next(
        app
        for app in list_external_apps_admin(action_admin, db_session)
        if app.openapi_tool_id == tool_id
    )
    assert response.id == app_id
    assert response.name == "Renamed while unavailable"
    assert not response.available_in_craft
    assert not response.enabled
    update_custom_tool(
        tool_id, CustomToolUpdate(available_in_craft=True), db_session, action_admin
    )
    assert _app(db_session, tool_id).id == app_id
    delete_custom_tool(tool_id, db_session, action_admin)
    assert (
        db_session.scalar(select(ExternalApp.id).where(ExternalApp.id == app_id))
        is None
    )


@pytest.mark.parametrize("source_enabled", [False, True])
def test_craft_availability_preserves_source_status_and_gateway_policies(
    db_session: Session, action_admin: User, source_enabled: bool
) -> None:
    tool_id = _create(db_session, action_admin)
    app_id = _app(db_session, tool_id).id
    gated_id = get_or_create_gated_app_id(db_session, GatedAppKind.EXTERNAL_APP, app_id)
    policies = {"GET https://openapi-test.example.com/v1/records": EndpointPolicy.DENY}
    replace_action_policies__no_commit(db_session, gated_id, policies)
    db_session.commit()
    update_tools_status(
        ToolStatusUpdateRequest(tool_ids=[tool_id], enabled=source_enabled),
        db_session,
        action_admin,
    )

    for available in (True, False, True):
        update_custom_tool(
            tool_id,
            CustomToolUpdate(available_in_craft=available),
            db_session,
            action_admin,
        )
        db_session.expire_all()
        tool = get_tool_by_id(tool_id, db_session)
        assert tool.enabled is source_enabled
        assert tool.available_in_craft is available
        response = next(
            app
            for app in list_external_apps_admin(action_admin, db_session)
            if app.openapi_tool_id == tool_id
        )
        assert response.id == app_id
        assert response.available_in_craft is available
        assert response.enabled is (available and source_enabled)
        assert (
            get_action_policies(db_session, GatedAppKind.EXTERNAL_APP, app_id)
            == policies
        )


def test_non_admin_owner_cannot_publish_or_change_published_action(
    db_session: Session, action_admin: User
) -> None:
    tool_id = _create(db_session, action_admin, enabled=False)
    action_admin.effective_permissions = [Permission.MANAGE_ACTIONS.value]
    db_session.commit()
    with pytest.raises(OnyxError) as error:
        update_custom_tool(
            tool_id, CustomToolUpdate(available_in_craft=True), db_session, action_admin
        )
    assert error.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    db_session.rollback()
    action_admin.effective_permissions = [Permission.FULL_ADMIN_PANEL_ACCESS.value]
    db_session.commit()
    update_custom_tool(
        tool_id, CustomToolUpdate(available_in_craft=True), db_session, action_admin
    )
    action_admin.effective_permissions = [Permission.MANAGE_ACTIONS.value]
    db_session.commit()
    with pytest.raises(OnyxError) as error:
        update_custom_tool(
            tool_id,
            CustomToolUpdate(definition=_schema("https://other.example.com")),
            db_session,
            action_admin,
        )
    assert error.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    db_session.rollback()
    assert _app(db_session, tool_id).enabled

    with pytest.raises(OnyxError) as error:
        update_custom_tool(
            tool_id,
            CustomToolUpdate(available_in_craft=False),
            db_session,
            action_admin,
        )
    assert error.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    db_session.rollback()
    assert get_tool_by_id(tool_id, db_session).available_in_craft

    with pytest.raises(OnyxError) as error:
        delete_custom_tool(tool_id, db_session, action_admin)
    assert error.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    db_session.rollback()
    with pytest.raises(OnyxError) as error:
        update_tools_status(
            ToolStatusUpdateRequest(tool_ids=[tool_id], enabled=False),
            db_session,
            action_admin,
        )
    assert error.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    db_session.rollback()
    assert _app(db_session, tool_id).enabled


def test_oauth_credentials_are_shared_with_chat_and_isolated_per_user(
    db_session: Session, action_admin: User, other_user: User, oauth_config: OAuthConfig
) -> None:
    config_id = oauth_config.id
    tool_id = create_custom_tool(
        CustomToolCreate(
            name="OAuth user isolation",
            definition=_schema(),
            passthrough_auth=False,
            oauth_config_id=config_id,
            available_in_craft=True,
            custom_headers=[Header(key="X-Workspace", value="workspace")],
        ),
        db_session,
        action_admin,
    ).id
    app = _app(db_session, tool_id)
    assert not app_is_available(db_session, app, action_admin.id)
    response = next(
        item
        for item in list_external_apps(action_admin, db_session)
        if item.id == app.id
    )
    assert not response.authenticated
    assert response.oauth_config_id == config_id
    assert response.supports_oauth
    with pytest.raises(ExternalAppCredentialsError):
        resolve_injection_headers(db_session, app.id, action_admin.id)
    upsert_user_oauth_token(
        config_id, action_admin.id, {"access_token": "owner-token"}, db_session
    )
    assert app_is_available(db_session, app, action_admin.id)
    assert resolve_injection_headers(db_session, app.id, action_admin.id) == {
        "Authorization": "Bearer owner-token",
        "X-Workspace": "workspace",
    }
    assert not app_is_available(db_session, app, other_user.id)
    with pytest.raises(ExternalAppCredentialsError):
        resolve_injection_headers(db_session, app.id, other_user.id)
    upsert_user_oauth_token(
        config_id, other_user.id, {"access_token": "other-token"}, db_session
    )
    assert resolve_injection_headers(db_session, app.id, other_user.id) == {
        "Authorization": "Bearer other-token",
        "X-Workspace": "workspace",
    }
    delete_user_oauth_token(config_id, action_admin.id, db_session)
    assert not app_is_available(db_session, app, action_admin.id)
    with pytest.raises(ExternalAppCredentialsError):
        resolve_injection_headers(db_session, app.id, action_admin.id)
    assert app_is_available(db_session, app, other_user.id)
    upsert_user_oauth_token(
        config_id,
        other_user.id,
        {
            "access_token": "expired-token",
            "expires_at": 1,
            "refresh_token": "refresh-token",
        },
        db_session,
    )
    # Availability checks must not contact the provider to refresh.
    assert app_is_available(db_session, app, other_user.id)
    response = next(
        item for item in list_external_apps(other_user, db_session) if item.id == app.id
    )
    assert response.authenticated
    upsert_user_oauth_token(
        config_id,
        other_user.id,
        {"access_token": "expired-token", "expires_at": 1},
        db_session,
    )
    assert not app_is_available(db_session, app, other_user.id)
    response = next(
        item for item in list_external_apps(other_user, db_session) if item.id == app.id
    )
    assert not response.authenticated


def test_passthrough_uses_each_users_login_token(
    db_session: Session, action_admin: User, other_user: User
) -> None:
    tool_id = create_custom_tool(
        CustomToolCreate(
            name="Login token isolation",
            definition=_schema(),
            passthrough_auth=True,
            available_in_craft=True,
            custom_headers=[Header(key="X-Workspace", value="workspace")],
        ),
        db_session,
        action_admin,
    ).id
    app = _app(db_session, tool_id)
    assert not app_is_available(db_session, app, action_admin.id)
    with pytest.raises(ExternalAppCredentialsError):
        resolve_injection_headers(db_session, app.id, action_admin.id)
    db_session.add(
        OAuthAccount(
            user_id=other_user.id,
            oauth_name="google",
            account_id=f"test-{other_user.id}",
            account_email=other_user.email,
            access_token="other-login-token",
        )
    )
    db_session.commit()
    db_session.expire_all()
    assert app_is_available(db_session, app, other_user.id)
    assert resolve_injection_headers(db_session, app.id, other_user.id) == {
        "Authorization": "Bearer other-login-token",
        "X-Workspace": "workspace",
    }
    with pytest.raises(ExternalAppCredentialsError):
        resolve_injection_headers(db_session, app.id, action_admin.id)


def test_linked_gateway_cannot_be_edited_or_deleted_from_apps(
    db_session: Session, action_admin: User
) -> None:
    tool_id = _create(db_session, action_admin)
    app_id = _app(db_session, tool_id).id
    with pytest.raises(OnyxError):
        update_external_app_admin(
            app_id,
            UpdateExternalAppRequest(
                upstream_url_patterns=["https://other.example.com/*"]
            ),
            action_admin,
            db_session,
        )
    db_session.rollback()
    with pytest.raises(OnyxError):
        delete_external_app_admin(app_id, action_admin, db_session)
    db_session.rollback()
    assert _app(db_session, tool_id).enabled


def test_invalid_headers_roll_back_source_and_gateway(
    db_session: Session, action_admin: User
) -> None:
    tool_id = _create(db_session, action_admin)
    with pytest.raises(OnyxError):
        update_custom_tool(
            tool_id,
            CustomToolUpdate(custom_headers=[Header(key="Bad Header", value="secret")]),
            db_session,
            action_admin,
        )
    db_session.rollback()
    tool = db_session.get(Tool, tool_id)
    assert tool is not None
    assert not tool.passthrough_auth
    assert resolve_injection_headers(
        db_session, _app(db_session, tool_id).id, action_admin.id
    ) == {"Authorization": _SECRET}


def test_source_credentials_cannot_be_overridden_by_user(
    db_session: Session, action_admin: User
) -> None:
    tool_id = _create(db_session, action_admin)
    app = _app(db_session, tool_id)
    with pytest.raises(OnyxError):
        upsert_user_credentials(
            app.id,
            UpsertUserCredentialsRequest(user_credentials={"header_0": "override"}),
            action_admin,
            db_session,
        )
    db_session.rollback()
    # Even a pre-existing credential row cannot replace the source secret.
    upsert_external_app_user_credential(
        db_session, app.id, action_admin.id, {"header_0": "override"}
    )
    assert resolve_injection_headers(db_session, app.id, action_admin.id) == {
        "Authorization": _SECRET
    }
    update_custom_tool(
        tool_id,
        CustomToolUpdate(custom_headers=[Header(key="X-API-Key", value="rotated")]),
        db_session,
        action_admin,
    )
    assert resolve_injection_headers(db_session, app.id, action_admin.id) == {
        "X-API-Key": "rotated"
    }
    update_custom_tool(
        tool_id, CustomToolUpdate(custom_headers=[]), db_session, action_admin
    )
    assert resolve_injection_headers(db_session, app.id, action_admin.id) == {}
    assert _app(db_session, tool_id).enabled


def test_linked_gateway_rejects_skill_associations(
    db_session: Session, action_admin: User
) -> None:
    tool_id = _create(db_session, action_admin)
    app_id = _app(db_session, tool_id).id
    with pytest.raises(OnyxError) as error:
        update_external_app_admin(
            app_id,
            UpdateExternalAppRequest(associated_skill_ids=[uuid4()]),
            action_admin,
            db_session,
        )
    assert error.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert "skill associations" in error.value.detail
    db_session.rollback()
    assert _app(db_session, tool_id).associated_skills == []


def test_omitted_oauth_configuration_is_preserved_when_publishing(
    db_session: Session, action_admin: User, oauth_config: OAuthConfig
) -> None:
    config_id = oauth_config.id
    tool_id = create_custom_tool(
        CustomToolCreate(
            name="OAuth action",
            definition=_schema(),
            passthrough_auth=False,
            oauth_config_id=config_id,
        ),
        db_session,
        action_admin,
    ).id
    updated = update_custom_tool(
        tool_id,
        CustomToolUpdate(name="Renamed OAuth action"),
        db_session,
        action_admin,
    )
    assert updated.oauth_config_id == config_id
    update_custom_tool(
        tool_id,
        CustomToolUpdate(available_in_craft=True),
        db_session,
        action_admin,
    )
    tool = get_tool_by_id(tool_id, db_session)
    assert tool.oauth_config_id == config_id
    assert tool.available_in_craft
    assert _app(db_session, tool_id).enabled
    # Explicit null still clears OAuth and permits static/no-auth publication.
    updated = update_custom_tool(
        tool_id,
        CustomToolUpdate(oauth_config_id=None, available_in_craft=True),
        db_session,
        action_admin,
    )
    assert updated.oauth_config_id is None
    assert _app(db_session, tool_id).enabled


def test_owner_edit_waits_for_publication_then_checks_admin_access(
    db_session: Session, action_admin: User
) -> None:
    tool_id = _create(db_session, action_admin, enabled=False)
    action_admin.effective_permissions = [Permission.MANAGE_ACTIONS.value]
    db_session.commit()
    owner_id = action_admin.id

    # Hold the publishing transaction open while the owner tries to edit.
    tool = get_tool_by_id(tool_id, db_session, for_update=True)
    tool.available_in_craft = True
    sync_openapi_external_app__no_commit(db_session, tool)
    with Session(db_session.get_bind()) as owner_session:
        owner = owner_session.get(User, owner_id)
        assert owner is not None
        owner_session.execute(text("SET LOCAL lock_timeout = '100ms'"))
        with pytest.raises(OperationalError, match="lock timeout") as lock_error:
            update_custom_tool(
                tool_id, CustomToolUpdate(name="Owner edit"), owner_session, owner
            )
        assert lock_error.value.statement is not None
        assert "FOR UPDATE" in lock_error.value.statement
        owner_session.rollback()
        db_session.commit()

        with pytest.raises(OnyxError) as error:
            update_custom_tool(
                tool_id, CustomToolUpdate(name="Owner edit"), owner_session, owner
            )
        assert error.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
        owner_session.rollback()
    db_session.expire_all()
    assert get_tool_by_id(tool_id, db_session).name == "Craft lifecycle"
    assert _app(db_session, tool_id).enabled


@pytest.mark.parametrize("bulk", [False, True])
def test_locked_tool_reads_refresh_cached_source_state(
    db_session: Session, action_admin: User, bulk: bool
) -> None:
    tool_id = _create(db_session, action_admin, enabled=False)
    cached = get_tool_by_id(tool_id, db_session)
    assert not cached.available_in_craft
    assert cached.craft_external_app is None
    with Session(db_session.get_bind()) as publisher:
        published = get_tool_by_id(tool_id, publisher, for_update=True)
        published.available_in_craft = True
        sync_openapi_external_app__no_commit(publisher, published)
        publisher.commit()
    assert not cached.available_in_craft
    locked = (
        get_tools_by_ids([tool_id], db_session, for_update=True)[0]
        if bulk
        else get_tool_by_id(tool_id, db_session, for_update=True)
    )
    assert locked is cached
    assert locked.available_in_craft
    assert locked.craft_external_app is not None
    db_session.rollback()


def test_oauth_mutations_reject_lock_conflicts_without_deadlocking(
    db_session: Session, action_admin: User, oauth_config: OAuthConfig
) -> None:
    config_id = oauth_config.id
    tool_id = create_custom_tool(
        CustomToolCreate(
            name="OAuth lock contention",
            definition=_schema(),
            passthrough_auth=False,
            oauth_config_id=config_id,
            available_in_craft=True,
        ),
        db_session,
        action_admin,
    ).id
    get_oauth_config(config_id, db_session, for_update=True)
    with Session(db_session.get_bind()) as concurrent_session:
        admin = concurrent_session.get(User, action_admin.id)
        assert admin is not None
        with pytest.raises(OnyxError) as error:
            update_oauth_config_endpoint(
                config_id,
                OAuthConfigUpdate(name="Conflicting edit"),
                concurrent_session,
                admin,
            )
        assert error.value.error_code == OnyxErrorCode.CONFLICT
        concurrent_session.rollback()
        # This route holds the Tool row before requesting its config lock.
        with pytest.raises(OnyxError) as error:
            update_custom_tool(
                tool_id,
                CustomToolUpdate(name="Conflicting action edit"),
                concurrent_session,
                admin,
            )
        assert error.value.error_code == OnyxErrorCode.CONFLICT
        concurrent_session.rollback()
        with pytest.raises(OnyxError) as error:
            delete_custom_tool(tool_id, concurrent_session, admin)
        assert error.value.error_code == OnyxErrorCode.CONFLICT
        concurrent_session.rollback()
    # FK SET NULL can now acquire the Tool row; no reverse-order lock wait remains.
    delete_oauth_config_endpoint(config_id, db_session, action_admin)
    db_session.expire_all()
    assert get_tool_by_id(tool_id, db_session).oauth_config_id is None


def test_operation_policies_match_routes_and_reset_when_destination_changes(
    db_session: Session, action_admin: User
) -> None:
    tool_id = _create(db_session, action_admin)
    schema = _schema()
    schema["paths"]["/records"]["post"] = {
        "operationId": "create_record",
        "summary": "Create record",
        "responses": {"200": {"description": "Created"}},
    }
    schema["paths"]["/records/{id}.json"] = {
        "get": {
            "operationId": "read_record",
            "summary": "Read record",
            "parameters": [
                {
                    "name": "id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "responses": {"200": {"description": "Record"}},
        }
    }
    schema["paths"]["/records/private.json"] = {
        "get": {
            "operationId": "read_private",
            "summary": "Read private record",
            "responses": {"200": {"description": "Record"}},
        }
    }
    update_custom_tool(
        tool_id, CustomToolUpdate(definition=schema), db_session, action_admin
    )
    app = _app(db_session, tool_id)
    response = next(
        row
        for row in list_external_apps_admin(action_admin, db_session)
        if row.id == app.id
    )
    actions = {(row.method, row.path): row for row in response.actions}
    assert all(row.state == EndpointPolicy.ASK for row in response.actions)
    read = actions[("GET", "/records")].action_id
    write = actions[("POST", "/records")].action_id
    record = actions[("GET", "/records/{id}.json")].action_id
    concrete = actions[("GET", "/records/private.json")].action_id
    update_external_app_admin(
        app.id,
        UpdateExternalAppRequest(
            action_policies={
                read: EndpointPolicy.ALWAYS,
                record: EndpointPolicy.DENY,
                concrete: EndpointPolicy.ALWAYS,
            }
        ),
        action_admin,
        db_session,
    )
    update_external_app_admin(
        app.id,
        UpdateExternalAppRequest(action_policies={write: EndpointPolicy.DENY}),
        action_admin,
        db_session,
    )
    for method, path, policy in [
        ("get", "/v1/records", EndpointPolicy.ALWAYS),
        ("POST", "/v1/records", EndpointPolicy.DENY),
        ("GET", "/v1/records/123.json", EndpointPolicy.DENY),
        ("GET", "/v1/records/private.json", EndpointPolicy.DENY),
        ("GET", "/v1/records/%0A.json", EndpointPolicy.DENY),
        ("GET", "/v1/temp/%2e%2e/records/123.json", EndpointPolicy.DENY),
        ("GET", "/v1%5crecords%5c123.json", EndpointPolicy.DENY),
        ("DELETE", "/v1/records", EndpointPolicy.ASK),
        ("GET", "/v1/unknown", EndpointPolicy.ASK),
    ]:
        request = ProxiedRequest(method=method, path=path)
        result = apply_credential_gate(
            app, request, recognize_actions(db_session, app, request), is_available=True
        )
        assert result is not None
        assert result.governing_action.policy == policy, (method, path)
    with pytest.raises(OnyxError, match="Unknown action"):
        update_external_app_admin(
            app.id,
            UpdateExternalAppRequest(
                action_policies={"invalid": EndpointPolicy.ALWAYS}
            ),
            action_admin,
            db_session,
        )
    db_session.rollback()
    reset = update_external_app_admin(
        app.id,
        UpdateExternalAppRequest(action_policies={read: EndpointPolicy.ASK}),
        action_admin,
        db_session,
    )
    assert (
        next(row for row in reset.actions if row.action_id == read).state
        == EndpointPolicy.ASK
    )
    assert (
        get_action_policies(db_session, GatedAppKind.EXTERNAL_APP, app.id)[write]
        == EndpointPolicy.DENY
    )
    schema["servers"] = [{"url": "https://replacement.example.com/v2"}]
    update_custom_tool(
        tool_id, CustomToolUpdate(definition=schema), db_session, action_admin
    )
    assert get_action_policies(db_session, GatedAppKind.EXTERNAL_APP, app.id) == {}
    response = next(
        row
        for row in list_external_apps_admin(action_admin, db_session)
        if row.id == app.id
    )
    assert all(row.state == EndpointPolicy.ASK for row in response.actions)
    assert all(
        "replacement.example.com/v2" in row.action_id for row in response.actions
    )


def test_operation_policy_api_requires_full_admin(
    db_session: Session, action_admin: User
) -> None:
    tool_id = _create(db_session, action_admin)
    app_id = _app(db_session, tool_id).id
    action_id = "GET https://openapi-test.example.com/v1/records"
    app = FastAPI()
    register_onyx_exception_handlers(app)
    app.include_router(admin_router)
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[current_user] = lambda: action_admin
    with TestClient(app) as client:
        action_admin.effective_permissions = [Permission.MANAGE_ACTIONS.value]
        db_session.commit()
        denied = client.patch(
            f"/apps/{app_id}", json={"action_policies": {action_id: "ALWAYS"}}
        )
        assert denied.status_code == 403
        assert get_action_policies(db_session, GatedAppKind.EXTERNAL_APP, app_id) == {}
        action_admin.effective_permissions = [Permission.FULL_ADMIN_PANEL_ACCESS.value]
        db_session.commit()
        allowed = client.patch(
            f"/apps/{app_id}", json={"action_policies": {action_id: "ALWAYS"}}
        )
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()["actions"][0]["state"] == "ALWAYS"


def test_legacy_invalid_catalog_does_not_break_admin_app_list(
    db_session: Session, action_admin: User
) -> None:
    tool_id = _create(db_session, action_admin)
    tool = get_tool_by_id(tool_id, db_session)
    schema = _schema()
    schema["paths"]["/records"]["get"]["servers"] = [
        {"url": "https://other.example.com"}
    ]
    tool.openapi_schema = schema
    db_session.commit()
    response = next(
        row
        for row in list_external_apps_admin(action_admin, db_session)
        if row.openapi_tool_id == tool_id
    )
    assert response.actions == []
    with pytest.raises(OnyxError, match="operation-level"):
        update_external_app_admin(
            response.id,
            UpdateExternalAppRequest(action_policies={}),
            action_admin,
            db_session,
        )
    db_session.rollback()
