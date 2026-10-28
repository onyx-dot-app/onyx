import pytest
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy import update
from sqlalchemy.orm import Session
from starlette.requests import Request

from onyx.auth.pat import hash_pat
from onyx.auth.permissions import has_permission, require_permission
from onyx.auth.users import UserManager, _resolve_optional_user
from onyx.db.engine.async_sql_engine import get_async_session_context_manager
from onyx.db.enums import Permission, PermissionAuthority
from onyx.db.models import OAuthAccount, PersonalAccessToken, User
from onyx.db.pat import create_pat, resolve_pat
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user


@pytest.mark.parametrize(
    "promotion", [Permission.FULL_ADMIN_PANEL_ACCESS, Permission.MANAGE_USER_GROUPS]
)
@pytest.mark.asyncio(loop_scope="module")
async def test_stored_manager_cap_and_child_preserve_authority(
    db_session: Session,
    promotion: Permission,
) -> None:
    user = create_test_user(db_session, "pat-authority", assign_default_group=False)
    try:
        user.effective_permissions = [
            Permission.BASIC_ACCESS.value,
            Permission.CREATE_USER_API_KEYS.value,
        ]
        user.is_group_manager = True
        db_session.commit()
        _, original = create_pat(db_session, user.id, "manager", None)
        db_session.commit()
        async with get_async_session_context_manager(
            POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
        ) as session:
            parent = await resolve_pat(hash_pat(original), session)
            assert parent is not None
            request = Request({"type": "http"})
            request.state.token_permission_cap = parent.permission_cap
            assert (
                await require_permission(
                    Permission.MANAGE_CONNECTORS, allow_scope=True
                )(request, parent.user)
            ).id == user.id

        user.effective_permissions = [Permission.BASIC_ACCESS.value, promotion.value]
        db_session.commit()
        if promotion is Permission.MANAGE_USER_GROUPS:
            assert (
                has_permission(user, Permission.MANAGE_CONNECTORS)
                is PermissionAuthority.SCOPED
            )
        _, child = create_pat(
            db_session, user.id, "child", None, parent_cap=parent.permission_cap
        )
        _, fresh = create_pat(db_session, user.id, "reissued", None)
        db_session.commit()

        for raw_token in (original, child, fresh):
            async with get_async_session_context_manager(
                POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
            ) as session:
                request = Request(
                    {
                        "type": "http",
                        "method": "GET",
                        "path": "/",
                        "headers": [(b"authorization", f"Bearer {raw_token}".encode())],
                    }
                )
                manager = UserManager(
                    SQLAlchemyUserDatabase(session, User, OAuthAccount)
                )
                if raw_token == fresh:
                    authenticated = await _resolve_optional_user(
                        request, session, None, manager
                    )
                    assert authenticated is not None
                    assert authenticated.id == user.id
                    assert (
                        await require_permission(
                            Permission.MANAGE_CONNECTORS, allow_scope=True
                        )(request, authenticated)
                    ).id == user.id
                else:
                    with pytest.raises(OnyxError) as error:
                        await _resolve_optional_user(request, session, None, manager)
                    assert (
                        error.value.error_code is OnyxErrorCode.INSUFFICIENT_PERMISSIONS
                    )
    finally:
        db_session.rollback()
        delete_test_user(db_session, user)
        db_session.commit()


@pytest.mark.asyncio(loop_scope="module")
async def test_legacy_flat_cap_fails_with_reissue_error(db_session: Session) -> None:
    user = create_test_user(db_session, "pat-flat-cap", assign_default_group=False)
    try:
        user.effective_permissions = [Permission.BASIC_ACCESS.value]
        record, token = create_pat(db_session, user.id, "old-format", None)
        db_session.execute(
            update(PersonalAccessToken)
            .where(PersonalAccessToken.id == record.id)
            .values(permission_cap=[Permission.READ_CHAT.value])
        )
        db_session.commit()
        async with get_async_session_context_manager(
            POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
        ) as session:
            request = Request(
                {
                    "type": "http",
                    "method": "GET",
                    "path": "/",
                    "headers": [(b"authorization", f"Bearer {token}".encode())],
                }
            )
            manager = UserManager(SQLAlchemyUserDatabase(session, User, OAuthAccount))
            with pytest.raises(OnyxError) as error:
                await _resolve_optional_user(request, session, None, manager)
            assert error.value.error_code is OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    finally:
        db_session.rollback()
        delete_test_user(db_session, user)
        db_session.commit()
