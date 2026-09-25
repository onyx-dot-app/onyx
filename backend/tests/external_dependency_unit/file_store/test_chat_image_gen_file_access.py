"""Scopes a generated file to the chat session that produced it.

`GET /chat/file/{file_id}` used to grant every `CHAT_IMAGE_GEN` file to any
authenticated user, so a leaked file id exposed another user's generated images
and code-interpreter outputs. Generated files are now stamped with their owning
chat session, and access follows the session: the owner, or anyone when the
session is shared as `PUBLIC`. Files written before the stamp existed carry no
session and keep the old behaviour so previously rendered images still load.
"""

from collections.abc import Generator
from typing import NamedTuple
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.access.access import user_can_access_chat_file
from onyx.configs.constants import CHAT_SESSION_ID_FILE_METADATA_KEY, FileOrigin
from onyx.db.chat import create_chat_session
from onyx.db.enums import ChatSessionSharedStatus
from onyx.db.models import ChatSession, FileRecord, User
from onyx.file_store.utils import chat_image_gen_metadata
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user


class _Users(NamedTuple):
    owner: User
    intruder: User
    created_file_ids: list[str]


@pytest.fixture
def users(db_session: Session) -> Generator[_Users, None, None]:
    owner = create_test_user(db_session, "img-gen-owner")
    intruder = create_test_user(db_session, "img-gen-intruder")
    created = _Users(owner=owner, intruder=intruder, created_file_ids=[])
    yield created
    db_session.rollback()
    db_session.query(FileRecord).filter(
        FileRecord.file_id.in_(created.created_file_ids)
    ).delete(synchronize_session=False)
    db_session.query(ChatSession).filter(
        ChatSession.user_id.in_([owner.id, intruder.id])
    ).delete(synchronize_session=False)
    delete_test_user(db_session, owner, intruder)
    db_session.commit()


def _new_session(db_session: Session, user_id: UUID) -> ChatSession:
    return create_chat_session(
        db_session=db_session,
        description="image gen access",
        user_id=user_id,
        persona_id=None,
    )


def _seed_generated_file(
    db_session: Session, users: _Users, file_metadata: dict[str, str] | None
) -> str:
    file_id = str(uuid4())
    db_session.add(
        FileRecord(
            file_id=file_id,
            display_name="GeneratedImage",
            file_origin=FileOrigin.CHAT_IMAGE_GEN,
            file_type="image/png",
            file_metadata=file_metadata,
            bucket_name="test-bucket",
            object_key=file_id,
        )
    )
    db_session.commit()
    users.created_file_ids.append(file_id)
    return file_id


def test_owner_can_read_their_generated_file(
    db_session: Session, users: _Users
) -> None:
    session = _new_session(db_session, users.owner.id)
    file_id = _seed_generated_file(
        db_session, users, chat_image_gen_metadata(session.id)
    )

    assert user_can_access_chat_file(file_id, users.owner, db_session)


def test_other_user_cannot_read_a_generated_file_from_a_private_session(
    db_session: Session, users: _Users
) -> None:
    session = _new_session(db_session, users.owner.id)
    file_id = _seed_generated_file(
        db_session, users, chat_image_gen_metadata(session.id)
    )

    assert not user_can_access_chat_file(file_id, users.intruder, db_session)


def test_other_user_can_read_a_generated_file_from_a_public_session(
    db_session: Session, users: _Users
) -> None:
    session = _new_session(db_session, users.owner.id)
    session.shared_status = ChatSessionSharedStatus.PUBLIC
    db_session.commit()
    file_id = _seed_generated_file(
        db_session, users, chat_image_gen_metadata(session.id)
    )

    assert user_can_access_chat_file(file_id, users.intruder, db_session)


def test_deleted_public_session_no_longer_shares_its_generated_file(
    db_session: Session, users: _Users
) -> None:
    session = _new_session(db_session, users.owner.id)
    session.shared_status = ChatSessionSharedStatus.PUBLIC
    session.deleted = True
    db_session.commit()
    file_id = _seed_generated_file(
        db_session, users, chat_image_gen_metadata(session.id)
    )

    assert not user_can_access_chat_file(file_id, users.intruder, db_session)


def test_legacy_unstamped_generated_file_stays_readable(
    db_session: Session, users: _Users
) -> None:
    file_id = _seed_generated_file(db_session, users, None)

    assert user_can_access_chat_file(file_id, users.intruder, db_session)


def test_malformed_session_stamp_is_denied(db_session: Session, users: _Users) -> None:
    file_id = _seed_generated_file(
        db_session, users, {CHAT_SESSION_ID_FILE_METADATA_KEY: "not-a-uuid"}
    )

    assert not user_can_access_chat_file(file_id, users.owner, db_session)
