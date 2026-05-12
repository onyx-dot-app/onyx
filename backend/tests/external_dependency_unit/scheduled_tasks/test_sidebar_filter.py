"""Tests that scheduled-run sessions are excluded from the Craft sidebar.

The sidebar query (`get_user_build_sessions`) filters on
`BuildSession.origin == INTERACTIVE`. The executor creates sessions
with `origin=SCHEDULED`, which must be invisible to the sidebar but
remain reachable directly by id (for the scheduled-run detail view).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from onyx.configs.constants import MessageType
from onyx.db.enums import SessionOrigin
from onyx.db.models import User
from onyx.server.features.build.db.build_session import create_build_session__no_commit
from onyx.server.features.build.db.build_session import create_message
from onyx.server.features.build.db.build_session import get_user_build_sessions


class TestSidebarOriginFilter:
    def test_only_interactive_sessions_listed(
        self,
        db_session: Session,
        test_user: User,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        # Interactive session (the kind the UI creates).
        interactive = create_build_session__no_commit(
            user_id=test_user.id,
            db_session=db_session,
            name="from UI",
            origin=SessionOrigin.INTERACTIVE,
        )
        # Add a message so `has_messages` matches.
        create_message(
            session_id=interactive.id,
            message_type=MessageType.USER,
            turn_index=0,
            message_metadata={
                "type": "user_message",
                "content": {"type": "text", "text": "hi"},
            },
            db_session=db_session,
        )

        # Scheduled-run session (executor-created).
        scheduled = create_build_session__no_commit(
            user_id=test_user.id,
            db_session=db_session,
            name="from scheduler",
            origin=SessionOrigin.SCHEDULED,
        )
        create_message(
            session_id=scheduled.id,
            message_type=MessageType.USER,
            turn_index=0,
            message_metadata={
                "type": "user_message",
                "content": {"type": "text", "text": "scheduled prompt"},
            },
            db_session=db_session,
        )
        db_session.commit()

        listed = get_user_build_sessions(test_user.id, db_session)
        listed_ids = {s.id for s in listed}
        assert interactive.id in listed_ids
        assert scheduled.id not in listed_ids
