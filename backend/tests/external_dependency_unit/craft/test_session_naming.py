"""Session naming with persisted messages and concurrent database writers."""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import MessageType
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import BuildSession, User
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.build.db.build_session import create_message
from onyx.server.features.build.session.manager import SessionManager
from onyx.server.features.build.session.naming import generate_session_name


@pytest.fixture
def unnamed_session(db_session: Session, build_session: BuildSession) -> BuildSession:
    build_session.name = None
    create_message(
        session_id=build_session.id,
        message_type=MessageType.USER,
        turn_index=0,
        message_metadata={
            "content": {"type": "text", "text": "  Build a ticket dashboard  "}
        },
        db_session=db_session,
    )
    db_session.commit()
    return build_session


@pytest.mark.parametrize(
    "output", ["", "   ", '"  "', RuntimeError("Model unavailable")]
)
def test_failed_or_empty_model_uses_first_message(
    db_session: Session,
    unnamed_session: BuildSession,
    test_user: User,
    output: str | Exception,
) -> None:
    llm = MagicMock()
    if isinstance(output, Exception):
        llm.invoke.side_effect = output
    else:
        llm.invoke.return_value.text = output
    with patch(
        "onyx.server.features.build.session.naming.get_default_llm", return_value=llm
    ):
        result = SessionManager(db_session).update_session_name(
            unnamed_session.id, test_user.id
        )
    assert result is not None
    assert result.name == "Build a ticket dashboard"
    db_session.expire_all()
    assert unnamed_session.name == "Build a ticket dashboard"


def test_empty_session_is_not_given_a_uuid_name(
    db_session: Session,
    build_session: BuildSession,
    test_user: User,
) -> None:
    build_session.name = None
    db_session.commit()
    with pytest.raises(OnyxError, match="Send a message"):
        SessionManager(db_session).update_session_name(build_session.id, test_user.id)
    db_session.refresh(build_session)
    assert build_session.name is None


def test_existing_name_is_preserved_without_model_call(
    db_session: Session,
    build_session: BuildSession,
    test_user: User,
) -> None:
    with patch("onyx.server.features.build.session.naming.get_default_llm") as get_llm:
        result = SessionManager(db_session).update_session_name(
            build_session.id, test_user.id
        )
    assert result is not None
    assert result.name == "Test Build Session"
    get_llm.assert_not_called()


@pytest.mark.parametrize("manual", [True, False])
def test_concurrent_name_wins_over_generation(
    db_session: Session,
    unnamed_session: BuildSession,
    test_user: User,
    manual: bool,
) -> None:
    session_id, user_id = unnamed_session.id, test_user.id

    def generate_with_concurrent_rename(*_args: object) -> str:
        with (
            get_session_with_current_tenant() as other_db,
            patch(
                "onyx.server.features.build.session.manager.generate_session_name",
                return_value="My chosen name",
            ),
        ):
            SessionManager(other_db).update_session_name(
                session_id, user_id, "My chosen name" if manual else None
            )
        return "Generated name"

    with patch(
        "onyx.server.features.build.session.manager.generate_session_name",
        side_effect=generate_with_concurrent_rename,
    ):
        result = SessionManager(db_session).update_session_name(session_id, user_id)
    assert result is not None
    assert result.name == "My chosen name"
    db_session.refresh(unnamed_session)
    assert unnamed_session.name == "My chosen name"


def test_generated_name_is_trimmed_and_bounded(
    db_session: Session,
    unnamed_session: BuildSession,
) -> None:
    llm = MagicMock()
    llm.invoke.return_value.text = '"' + "Dashboard " * 10 + '"'
    with patch(
        "onyx.server.features.build.session.naming.get_default_llm", return_value=llm
    ):
        name = generate_session_name(db_session, unnamed_session.id)
    assert name == ("Dashboard " * 10)[:47] + "..."
