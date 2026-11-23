"""Deleting a user deletes their profile photo file on both delete paths."""

import io

import pytest
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy.orm import Session

from onyx.auth.users import UserManager
from onyx.configs.constants import FileOrigin
from onyx.db.engine.async_sql_engine import get_async_session_context_manager
from onyx.db.file_record import get_filerecord_by_file_id_optional
from onyx.db.models import User
from onyx.db.users import delete_user_from_db
from onyx.file_store.file_store import get_default_file_store
from onyx.server.manage.profile_image import PROFILE_IMAGE_MIME_TYPE
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.conftest import (
    create_test_user,
    delete_test_user,
)


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize("delete_path", ["admin", "auth"])
async def test_deleting_a_user_deletes_their_profile_photo(
    db_session: Session,
    delete_path: str,
) -> None:
    user = create_test_user(db_session, "photo-owner")
    user_id = user.id
    file_id: str | None = None
    try:
        file_id = get_default_file_store().save_file(
            content=io.BytesIO(b"photo"),
            display_name=f"profile-image-{user_id}",
            file_origin=FileOrigin.USER_PROFILE_IMAGE,
            file_type=PROFILE_IMAGE_MIME_TYPE,
        )
        user.profile_image_file_id = file_id
        db_session.commit()
        if delete_path == "admin":
            delete_user_from_db(user, db_session)
        else:
            async with get_async_session_context_manager(
                get_current_tenant_id()
            ) as session:
                async_user = await session.get(User, user_id)
                assert async_user is not None
                await UserManager(SQLAlchemyUserDatabase(session, User)).delete(
                    async_user
                )

        db_session.expire_all()
        assert db_session.get(User, user_id) is None
        assert get_filerecord_by_file_id_optional(file_id, db_session) is None
    finally:
        db_session.expire_all()
        remaining_user = db_session.get(User, user_id)
        if remaining_user is not None:
            delete_test_user(db_session, remaining_user)
            db_session.commit()
        if (
            file_id is not None
            and get_filerecord_by_file_id_optional(file_id, db_session) is not None
        ):
            get_default_file_store().delete_file(file_id)
