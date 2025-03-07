import random
from datetime import datetime
from datetime import timedelta

from onyx.configs.constants import MessageType
from onyx.db.chat import create_chat_session
from onyx.db.chat import create_new_chat_message
from onyx.db.chat import get_or_create_root_message
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.models import ChatSession


def seed_chat_history(num_sessions: int, num_messages: int, days: int) -> None:
    """Utility function to seed chat history for testing.

    num_sessions: the number of sessions to seed
    num_messages: the number of messages to seed per sessions
    days: the number of days looking backwards from the current time over which to randomize
    the times.
    """
    with get_session_with_current_tenant() as db_session:
        for y in range(0, num_sessions):
            create_chat_session(db_session, f"pytest_session_{y}", None, None)

        # randomize all session times
        rows = db_session.query(ChatSession).all()
        for row in rows:
            row.time_created = datetime.utcnow() - timedelta(
                days=random.randint(0, days)
            )
            row.time_updated = row.time_created + timedelta(
                minutes=random.randint(0, 10)
            )

            root_message = get_or_create_root_message(row.id, db_session)

            for x in range(0, num_messages):
                chat_message = create_new_chat_message(
                    row.id,
                    root_message,
                    f"pytest_message_{x}",
                    None,
                    0,
                    MessageType.USER,
                    db_session,
                )

                chat_message.time_sent = row.time_created + timedelta(
                    minutes=random.randint(0, 10)
                )
            db_session.commit()

        db_session.commit()
