from sqlalchemy.orm import Session

from onyx.configs.constants import MessageType
from onyx.db.chat import build_chat_history_to_message
from onyx.db.chat import create_chat_session
from onyx.db.chat import create_new_chat_message
from onyx.db.chat import get_or_create_root_message
from onyx.db.models import ChatMessage
from onyx.db.models import Persona
from tests.external_dependency_unit.conftest import create_test_user


def _add_message(
    db_session: Session,
    chat_session_id: "ChatMessage.chat_session_id.type",
    parent: ChatMessage,
    text: str,
    message_type: MessageType,
) -> ChatMessage:
    msg = create_new_chat_message(
        chat_session_id=chat_session_id,
        parent_message=parent,
        message=text,
        token_count=0,
        message_type=message_type,
        db_session=db_session,
        commit=True,
    )
    parent.latest_child_message_id = msg.id
    db_session.commit()
    return msg


def test_build_chat_history_to_message_off_mainline(db_session: Session) -> None:
    """A non-mainline parent should resolve via the immutable parent chain
    and rewrite ``latest_child_message_id`` so the mainline matches the path
    we just used.

    Tree (root excluded from chain):
        root → U1 → A1 → U2 → A2 (mainline)
                       └─ A1' (sibling assistant response, off mainline)
    Calling with target=A1' should return chain [U1, A1'] and update
    root.latest_child_message_id = U1, U1.latest_child_message_id = A1'.
    """
    user = create_test_user(db_session, "build-chain")
    persona = Persona(name="build-chain-test", description="test")
    db_session.add(persona)
    db_session.flush()

    chat_session = create_chat_session(
        db_session=db_session,
        description="test",
        user_id=user.id,
        persona_id=persona.id,
    )
    root = get_or_create_root_message(
        chat_session_id=chat_session.id, db_session=db_session
    )

    u1 = _add_message(db_session, chat_session.id, root, "u1", MessageType.USER)
    a1 = _add_message(db_session, chat_session.id, u1, "a1", MessageType.ASSISTANT)
    u2 = _add_message(db_session, chat_session.id, a1, "u2", MessageType.USER)
    _a2 = _add_message(db_session, chat_session.id, u2, "a2", MessageType.ASSISTANT)

    # Branch: alternate assistant response to u1. ``create_new_chat_message``
    # updates ``u1.latest_child_message_id`` to point at the new child, so we
    # manually reset it to ``a1`` to simulate the exact race we're fixing:
    # the client has locally flipped to ``a1_prime`` but its
    # ``set-message-as-latest`` PUT has not yet rewritten the mainline pointer.
    a1_prime = create_new_chat_message(
        chat_session_id=chat_session.id,
        parent_message=u1,
        message="a1_prime",
        token_count=0,
        message_type=MessageType.ASSISTANT,
        db_session=db_session,
        commit=True,
    )
    u1.latest_child_message_id = a1.id
    db_session.commit()

    db_session.refresh(u1)
    assert u1.latest_child_message_id == a1.id  # mainline still on a1

    target, chain = build_chat_history_to_message(
        chat_session_id=chat_session.id,
        target_message_id=a1_prime.id,
        db_session=db_session,
    )

    assert target.id == a1_prime.id
    assert [m.id for m in chain] == [u1.id, a1_prime.id]

    # Mainline should have been rewritten along the path we just used.
    db_session.refresh(root)
    db_session.refresh(u1)
    assert root.latest_child_message_id == u1.id
    assert u1.latest_child_message_id == a1_prime.id


def test_build_chat_history_to_message_invalid_id(db_session: Session) -> None:
    """A parent_message_id that does not belong to the session must raise."""
    user = create_test_user(db_session, "build-chain-invalid")
    persona = Persona(name="build-chain-invalid", description="test")
    db_session.add(persona)
    db_session.flush()

    chat_session = create_chat_session(
        db_session=db_session,
        description="test",
        user_id=user.id,
        persona_id=persona.id,
    )

    try:
        build_chat_history_to_message(
            chat_session_id=chat_session.id,
            target_message_id=-99999,
            db_session=db_session,
        )
    except ValueError as e:
        assert "not found in chat session" in str(e)
    else:
        raise AssertionError("Expected ValueError for missing message id")
