"""Owner scoping for the "Continue Chat in Onyx!" seed path
(`duplicate_chat_session_for_user_from_slack`)."""

from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from onyx.configs.constants import ANONYMOUS_USER_UUID
from onyx.db.chat import create_chat_session, duplicate_chat_session_for_user_from_slack
from onyx.db.models import ChatSession
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from tests.external_dependency_unit.conftest import create_test_user


def _session_count(db_session: Session, user_id: UUID) -> int:
    return (
        db_session.scalar(
            select(func.count())
            .select_from(ChatSession)
            .where(ChatSession.user_id == user_id)
        )
        or 0
    )


def test_cannot_seed_from_another_users_session(db_session: Session) -> None:
    attacker = create_test_user(db_session, "seed_attacker")
    victim = create_test_user(db_session, "seed_victim")
    victim_session = create_chat_session(
        db_session=db_session,
        description="victim private chat",
        user_id=victim.id,
        persona_id=None,
    )

    with pytest.raises(OnyxError) as exc_info:
        duplicate_chat_session_for_user_from_slack(
            db_session=db_session,
            user=attacker,
            chat_session_id=victim_session.id,
        )
    assert exc_info.value.error_code == OnyxErrorCode.SESSION_NOT_FOUND
    assert _session_count(db_session, attacker.id) == 0


@pytest.mark.parametrize("owner", ["caller", "unowned", "anonymous"])
def test_can_seed_from_slack_owned_session(db_session: Session, owner: str) -> None:
    # Slack DMs/ephemeral replies are owned by the mapped user; public channel
    # replies by the anonymous user; pre-migration rows may have no owner.
    user = create_test_user(db_session, "seed_user")
    owner_id = {
        "caller": user.id,
        "unowned": None,
        "anonymous": UUID(ANONYMOUS_USER_UUID),
    }[owner]
    source = create_chat_session(
        db_session=db_session,
        description="",
        user_id=owner_id,
        persona_id=None,
    )

    new_session = duplicate_chat_session_for_user_from_slack(
        db_session=db_session,
        user=user,
        chat_session_id=source.id,
    )

    assert new_session.id != source.id
    assert new_session.user_id == user.id
