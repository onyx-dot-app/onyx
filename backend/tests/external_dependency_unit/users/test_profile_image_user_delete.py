"""Deleting a user deletes their profile photo file on every delete path."""

import io
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ee.onyx.server.tenants.team_membership_api import leave_organization
from onyx.auth.users import UserManager
from onyx.configs.constants import FileOrigin
from onyx.db.discord_bot import (
    get_discord_service_api_key,
    get_or_create_discord_service_api_key,
)
from onyx.db.engine.async_sql_engine import get_async_session_context_manager
from onyx.db.file_record import get_filerecord_by_file_id_optional
from onyx.db.models import ApiKey, User
from onyx.db.users import delete_user_from_db
from onyx.file_store.file_store import get_default_file_store
from onyx.server.manage.discord_bot.api import delete_service_api_key_endpoint
from onyx.server.manage.models import UserByEmail
from onyx.server.manage.profile_image import PROFILE_IMAGE_MIME_TYPE
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.conftest import (
    create_test_user,
    delete_test_user,
)


@pytest.fixture
def users_to_clean_up(db_session: Session) -> Generator[list[UUID], None, None]:
    """Deletes the users that a failed test appends, with their API keys and
    profile photos."""
    user_ids: list[UUID] = []
    yield user_ids
    db_session.rollback()
    db_session.expire_all()
    for user_id in user_ids:
        user = db_session.get(User, user_id)
        if user is None:
            continue
        file_id = user.profile_image_file_id
        db_session.execute(delete(ApiKey).where(ApiKey.user_id == user_id))
        delete_test_user(db_session, user)
        db_session.commit()
        if file_id is not None:
            get_default_file_store().delete_file(file_id, error_on_missing=False)


def _attach_profile_photo(db_session: Session, user: User) -> str:
    file_id = get_default_file_store().save_file(
        content=io.BytesIO(b"photo"),
        display_name=f"profile-image-{user.id}",
        file_origin=FileOrigin.USER_PROFILE_IMAGE,
        file_type=PROFILE_IMAGE_MIME_TYPE,
    )
    user.profile_image_file_id = file_id
    db_session.commit()
    return file_id


def _assert_user_and_photo_gone(
    db_session: Session, user_id: UUID, file_id: str
) -> None:
    db_session.expire_all()
    assert db_session.get(User, user_id) is None
    assert get_filerecord_by_file_id_optional(file_id, db_session) is None


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize("delete_path", ["admin", "auth"])
async def test_deleting_a_user_deletes_their_profile_photo(
    db_session: Session,
    users_to_clean_up: list[UUID],
    delete_path: str,
) -> None:
    user = create_test_user(db_session, "photo-owner")
    user_id = user.id
    users_to_clean_up.append(user_id)
    file_id = _attach_profile_photo(db_session, user)

    if delete_path == "admin":
        delete_user_from_db(user, db_session)
    else:
        async with get_async_session_context_manager(
            get_current_tenant_id()
        ) as session:
            async_user = await session.get(User, user_id)
            assert async_user is not None
            await UserManager(SQLAlchemyUserDatabase(session, User)).delete(async_user)

    _assert_user_and_photo_gone(db_session, user_id, file_id)


def test_deleting_the_discord_service_key_deletes_its_user_photo(
    db_session: Session, users_to_clean_up: list[UUID]
) -> None:
    get_or_create_discord_service_api_key(db_session, get_current_tenant_id())
    db_session.commit()
    service_key = get_discord_service_api_key(db_session)
    assert service_key is not None
    service_user = db_session.get(User, service_key.user_id)
    assert service_user is not None
    service_user_id = service_user.id
    users_to_clean_up.append(service_user_id)
    file_id = _attach_profile_photo(db_session, service_user)

    delete_service_api_key_endpoint(MagicMock(), db_session)

    _assert_user_and_photo_gone(db_session, service_user_id, file_id)


@pytest.mark.asyncio(loop_scope="module")
async def test_last_admin_leaving_deletes_their_profile_photo(
    db_session: Session, users_to_clean_up: list[UUID]
) -> None:
    admin = create_test_user(db_session, "last-admin", is_admin=True)
    admin_id = admin.id
    users_to_clean_up.append(admin_id)
    file_id = _attach_profile_photo(db_session, admin)

    module = "ee.onyx.server.tenants.team_membership_api"
    with (
        patch(f"{module}.get_user_count", AsyncMock(return_value=1)),
        patch(f"{module}.delete_user_from_control_plane", AsyncMock()),
        patch(f"{module}.remove_all_users_from_tenant"),
        patch(f"{module}.purge_harness_sandboxes"),
    ):
        await leave_organization(UserByEmail(user_email=admin.email), admin, db_session)

    _assert_user_and_photo_gone(db_session, admin_id, file_id)
