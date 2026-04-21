"""Regression tests for `user_can_access_chat_file` covering image-generation
outputs, which are persisted on `ToolCall.generated_images` (JSONB) rather than
on `ChatMessage.files`.

Before the fix in `backend/onyx/db/user_file.py`, the access check only looked at
`UserFile`, persona avatars, and `ChatMessage.files`. As a result, any image
returned by `ImageGenerationTool` would 404 from `GET /chat/file/{file_id}` even
for the chat session's own owner. These tests pin the post-fix behavior:

- `test_owner_can_access_image_gen_file_via_tool_call` fails on the pre-fix code
  and passes on the post-fix code — that pair is the regression proof.
- The other tests guard against over-permissive access (cross-user reads on
  private sessions, unrelated file ids).
"""

from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.db.chat import create_chat_session
from onyx.db.enums import ChatSessionSharedStatus
from onyx.db.models import ToolCall
from onyx.db.user_file import user_can_access_chat_file
from tests.external_dependency_unit.conftest import create_test_user


def _add_image_gen_tool_call(
    db_session: Session, chat_session_id, file_id: str
) -> ToolCall:
    tool_call = ToolCall(
        chat_session_id=chat_session_id,
        parent_chat_message_id=None,
        parent_tool_call_id=None,
        turn_number=0,
        tab_index=0,
        tool_id=0,
        tool_call_id=uuid4().hex,
        tool_call_arguments={},
        tool_call_response="",
        tool_call_tokens=0,
        generated_images=[
            {
                "file_id": file_id,
                "url": f"/api/chat/file/{file_id}",
                "revised_prompt": "a cat",
                "shape": "square",
            }
        ],
    )
    db_session.add(tool_call)
    db_session.flush()
    return tool_call


def test_owner_can_access_image_gen_file_via_tool_call(
    db_session: Session,
) -> None:
    """The session owner must be able to fetch an image-gen file_id that lives
    on ToolCall.generated_images. This is the pre/post-fix regression check."""
    owner = create_test_user(db_session, "img-gen-owner")
    chat_session = create_chat_session(
        db_session=db_session,
        description="image gen test",
        user_id=owner.id,
        persona_id=None,
    )
    file_id = uuid4().hex
    tool_call = _add_image_gen_tool_call(db_session, chat_session.id, file_id)

    try:
        assert user_can_access_chat_file(file_id, owner.id, db_session) is True
    finally:
        db_session.delete(tool_call)
        db_session.delete(chat_session)
        db_session.commit()


def test_other_user_cannot_access_image_gen_file_in_private_session(
    db_session: Session,
) -> None:
    """A non-owner must not be able to read an image-gen file in a PRIVATE
    session — the new branch should not over-grant access."""
    owner = create_test_user(db_session, "img-gen-owner-priv")
    intruder = create_test_user(db_session, "img-gen-intruder")
    chat_session = create_chat_session(
        db_session=db_session,
        description="private image gen",
        user_id=owner.id,
        persona_id=None,
    )
    # create_chat_session defaults to PRIVATE; assert to make the intent
    # explicit and catch any future default change.
    assert chat_session.shared_status == ChatSessionSharedStatus.PRIVATE
    file_id = uuid4().hex
    tool_call = _add_image_gen_tool_call(db_session, chat_session.id, file_id)

    try:
        assert user_can_access_chat_file(file_id, intruder.id, db_session) is False
    finally:
        db_session.delete(tool_call)
        db_session.delete(chat_session)
        db_session.commit()


def test_other_user_can_access_image_gen_file_in_public_session(
    db_session: Session,
) -> None:
    """When a chat session is publicly shared, any authenticated user must be
    able to fetch its image-gen outputs — mirroring the existing
    ChatMessage.files branch behavior."""
    owner = create_test_user(db_session, "img-gen-owner-pub")
    viewer = create_test_user(db_session, "img-gen-viewer")
    chat_session = create_chat_session(
        db_session=db_session,
        description="public image gen",
        user_id=owner.id,
        persona_id=None,
    )
    chat_session.shared_status = ChatSessionSharedStatus.PUBLIC
    db_session.flush()
    file_id = uuid4().hex
    tool_call = _add_image_gen_tool_call(db_session, chat_session.id, file_id)

    try:
        assert user_can_access_chat_file(file_id, viewer.id, db_session) is True
    finally:
        db_session.delete(tool_call)
        db_session.delete(chat_session)
        db_session.commit()


def test_unrelated_file_id_returns_false(db_session: Session) -> None:
    """An arbitrary file_id that exists nowhere should return False — guards
    against the new branch matching on something other than the JSONB
    containment."""
    user = create_test_user(db_session, "img-gen-noise")
    assert user_can_access_chat_file(uuid4().hex, user.id, db_session) is False
