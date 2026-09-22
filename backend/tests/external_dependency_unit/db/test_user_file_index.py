"""Indexing an existing store blob must reuse one UserFile and promote it."""

from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import FileOrigin
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import UserFileStatus
from onyx.db.file_record import get_incognito_file_ids
from onyx.db.models import User, UserFile
from onyx.db.user_file import get_or_create_user_file_for_existing_store_file
from onyx.file_store.file_store import get_default_file_store
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from shared_configs.contextvars import (
    CURRENT_CONTENT_FREE_SESSION_ID_CONTEXTVAR,
    CURRENT_TENANT_ID_CONTEXTVAR,
)
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user


@pytest.fixture
def owner(db_session: Session) -> Generator[User, None, None]:
    user = create_test_user(db_session, "user-file-index")
    yield user

    db_session.rollback()
    file_ids = [
        file_id
        for (file_id,) in db_session.query(UserFile.file_id)
        .filter(UserFile.user_id == user.id)
        .all()
    ]
    db_session.query(UserFile).filter(UserFile.user_id == user.id).delete()
    db_session.commit()
    file_store = get_default_file_store()
    for file_id in file_ids:
        file_store.delete_file(file_id, error_on_missing=False)
    delete_test_user(db_session, user)
    db_session.commit()


def _save_blob(session_id: UUID | None = None) -> str:
    token = None
    if session_id is not None:
        token = CURRENT_CONTENT_FREE_SESSION_ID_CONTEXTVAR.set(str(session_id))
    try:
        return get_default_file_store().save_file(
            content=BytesIO(b"generated image bytes"),
            display_name="chart.png",
            file_origin=FileOrigin.CHAT_IMAGE_GEN,
            file_type="image/png",
        )
    finally:
        if token is not None:
            CURRENT_CONTENT_FREE_SESSION_ID_CONTEXTVAR.reset(token)


def test_get_or_create_is_idempotent(db_session: Session, owner: User) -> None:
    file_id = _save_blob()

    first = get_or_create_user_file_for_existing_store_file(
        user_id=owner.id,
        file_id=file_id,
        name="chart.png",
        content_type="image/png",
        db_session=db_session,
    )
    second = get_or_create_user_file_for_existing_store_file(
        user_id=owner.id,
        file_id=file_id,
        name="other-name.png",
        content_type="image/png",
        db_session=db_session,
    )

    assert first.id == second.id
    assert (
        db_session.query(UserFile)
        .filter(UserFile.user_id == owner.id, UserFile.file_id == file_id)
        .count()
        == 1
    )


def test_get_or_create_is_idempotent_under_concurrency(
    db_session: Session, owner: User
) -> None:
    file_id = _save_blob()
    user_id = owner.id

    def _create() -> UUID:
        CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
        with get_session_with_current_tenant() as session:
            return get_or_create_user_file_for_existing_store_file(
                user_id=user_id,
                file_id=file_id,
                name="chart.png",
                content_type="image/png",
                db_session=session,
            ).id

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_create) for _ in range(8)]
        created_ids = [future.result() for future in as_completed(futures)]

    assert len(set(created_ids)) == 1
    assert (
        db_session.query(UserFile)
        .filter(UserFile.user_id == owner.id, UserFile.file_id == file_id)
        .count()
        == 1
    )


def test_get_or_create_survives_concurrent_delete(
    db_session: Session, owner: User
) -> None:
    file_id = _save_blob()
    existing = get_or_create_user_file_for_existing_store_file(
        user_id=owner.id,
        file_id=file_id,
        name="chart.png",
        content_type="image/png",
        db_session=db_session,
    )
    existing_id = existing.id
    user_id = owner.id

    def _index() -> UUID:
        CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
        with get_session_with_current_tenant() as session:
            return get_or_create_user_file_for_existing_store_file(
                user_id=user_id,
                file_id=file_id,
                name="chart.png",
                content_type="image/png",
                db_session=session,
            ).id

    def _delete() -> None:
        CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
        with get_session_with_current_tenant() as session:
            user_file = session.get(UserFile, existing_id)
            if user_file is not None:
                session.delete(user_file)
                session.commit()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(_index), executor.submit(_delete)]
        for future in as_completed(futures):
            future.result()

    remaining = (
        db_session.query(UserFile)
        .filter(UserFile.user_id == owner.id, UserFile.file_id == file_id)
        .all()
    )
    assert len(remaining) <= 1


def test_get_or_create_inserts_again_after_hard_delete(
    db_session: Session, owner: User
) -> None:
    file_id = _save_blob()
    first = get_or_create_user_file_for_existing_store_file(
        user_id=owner.id,
        file_id=file_id,
        name="chart.png",
        content_type="image/png",
        db_session=db_session,
    )
    first_id = first.id
    db_session.delete(first)
    db_session.commit()

    second = get_or_create_user_file_for_existing_store_file(
        user_id=owner.id,
        file_id=file_id,
        name="chart.png",
        content_type="image/png",
        db_session=db_session,
    )

    assert second.id != first_id
    assert second.status == UserFileStatus.PROCESSING
    assert (
        db_session.query(UserFile)
        .filter(UserFile.user_id == owner.id, UserFile.file_id == file_id)
        .count()
        == 1
    )


def test_get_or_create_does_not_replace_a_deleting_row(
    db_session: Session, owner: User
) -> None:
    file_id = _save_blob()
    existing = get_or_create_user_file_for_existing_store_file(
        user_id=owner.id,
        file_id=file_id,
        name="chart.png",
        content_type="image/png",
        db_session=db_session,
    )
    existing.status = UserFileStatus.DELETING
    db_session.commit()

    result = get_or_create_user_file_for_existing_store_file(
        user_id=owner.id,
        file_id=file_id,
        name="chart.png",
        content_type="image/png",
        db_session=db_session,
    )

    assert result.id == existing.id
    assert result.status == UserFileStatus.DELETING
    assert (
        db_session.query(UserFile)
        .filter(UserFile.user_id == owner.id, UserFile.file_id == file_id)
        .count()
        == 1
    )


def test_indexing_clears_incognito_blob_stamp(db_session: Session, owner: User) -> None:
    session_id = uuid4()
    file_id = _save_blob(session_id)
    assert get_incognito_file_ids(str(session_id), db_session) == [file_id]

    user_file = get_or_create_user_file_for_existing_store_file(
        user_id=owner.id,
        file_id=file_id,
        name="chart.png",
        content_type="image/png",
        db_session=db_session,
    )

    assert user_file.incognito is False
    assert user_file.incognito_session_id is None
    assert get_incognito_file_ids(str(session_id), db_session) == []
