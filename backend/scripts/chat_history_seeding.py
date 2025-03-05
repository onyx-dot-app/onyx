import argparse
import logging
import random
from datetime import datetime
from datetime import timedelta
from logging import getLogger

from onyx.configs.constants import MessageType
from onyx.db.chat import create_chat_session
from onyx.db.chat import create_new_chat_message
from onyx.db.chat import get_or_create_root_message
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.models import ChatSession

# Configure the logger
logging.basicConfig(
    level=logging.INFO,  # Set the log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",  # Log format
    handlers=[logging.StreamHandler()],  # Output logs to console
)

logger = getLogger(__name__)


def go_main(num_sessions: int, num_messages: int) -> None:
    with get_session_with_current_tenant() as db_session:
        for y in range(0, num_sessions):
            create_chat_session(db_session, f"pytest_session_{y}", None, None)

        # randomize all session times
        rows = db_session.query(ChatSession).all()
        for row in rows:
            row.time_created = datetime.utcnow() - timedelta(days=random.randint(0, 90))
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sample API Usage - Seed chat history")
    parser.add_argument(
        "--sessions",
        type=int,
        default=2048,
        help="Number of chat sessions to seed",
    )

    parser.add_argument(
        "--messages",
        type=int,
        default=4,
        help="Number of chat messages to seed per session",
    )

    args = parser.parse_args()
    go_main(args.sessions, args.messages)
