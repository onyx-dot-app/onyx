import random
from datetime import datetime
from datetime import timedelta
from logging import getLogger

from onyx.configs.constants import MessageType
from onyx.db.chat import create_chat_session
from onyx.db.chat import create_new_chat_message
from onyx.db.chat import get_or_create_root_message
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ChatSession

logger = getLogger(__name__)


def seed_chat_history(num_sessions: int, num_messages: int, days: int) -> None:
    """Utility function to seed chat history for testing.

    num_sessions: the number of sessions to seed
    num_messages: the number of messages to seed per sessions
    days: the number of days looking backwards from the current time over which to randomize
    the times.
    """
    with get_session_with_current_tenant() as db_session:
        logger.info(f"Seeding {num_sessions} sessions.")
        for y in range(0, num_sessions):
            create_chat_session(db_session, f"pytest_session_{y}", None, None)

        # randomize all session times
        logger.info(f"Seeding {num_messages} messages per session.")
        rows = db_session.query(ChatSession).all()
        for x in range(0, len(rows)):
            if x % 1024 == 0:
                logger.info(f"Seeded messages for {x} sessions so far.")

            row = rows[x]
            row.time_created = datetime.utcnow() - timedelta(
                days=random.randint(0, days)
            )
            row.time_updated = row.time_created + timedelta(
                minutes=random.randint(0, 10)
            )

            root_message = get_or_create_root_message(row.id, db_session)

            current_message_type = MessageType.USER
            parent_message = root_message
            for x in range(0, num_messages):
                if current_message_type == MessageType.USER:
                    msg = f"pytest_message_user_{x}"
                else:
                    msg = f"pytest_message_assistant_{x}"

                chat_message = create_new_chat_message(
                    chat_session_id=row.id,
                    parent_message=parent_message,
                    message=msg,
                    token_count=0,
                    message_type=current_message_type,
                    commit=False,
                    db_session=db_session,
                )

                chat_message.time_sent = row.time_created + timedelta(
                    minutes=random.randint(0, 10)
                )

                db_session.commit()

                current_message_type = (
                    MessageType.ASSISTANT
                    if current_message_type == MessageType.USER
                    else MessageType.USER
                )
                parent_message = chat_message

        db_session.commit()

        logger.info(f"Seeded messages for {len(rows)} sessions. Finished.")
